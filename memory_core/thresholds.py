"""Persistent incremental-token scheduling; not a long-context model adapter.

Queue visibility and completion are authoritative. Counts are cached once per
source/counter, rather than repeatedly tokenizing the accumulated transcript.
The reported per-message count is an estimate, never provider usage.
"""
import json
import time
import uuid


class ThresholdScheduler:
    def __init__(self, core):
        self.core = core
        self.db = core.store.db
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS source_token_counts(
            source_id TEXT PRIMARY KEY, counter TEXT, tokens INTEGER);
          CREATE TABLE IF NOT EXISTS extraction_triggers(
            session_id TEXT PRIMARY KEY, claim_id TEXT, lease_until REAL DEFAULT 0,
            retry_after REAL DEFAULT 0, continuation INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS extraction_trigger_events(
            id TEXT PRIMARY KEY, session_id TEXT, started_at REAL, finished_at REAL,
            threshold_tokens INTEGER, pending_tokens_before INTEGER,
            pending_tokens_after INTEGER, state TEXT, model_calls INTEGER, error TEXT);
        ''')

    @property
    def counter(self):
        return self.core.tokens.name + ':role_text_per_message_v1'

    def _backfill(self, session_id):
        # Also supports queues created before token scheduling was installed.
        rows = self.db.execute('''
          SELECT i.id,i.payload FROM inbox i JOIN controls c ON c.source_id=i.id
          LEFT JOIN source_token_counts t ON t.source_id=i.id
          WHERE i.session_id=? AND i.state NOT IN ('done','deleted','cancelled')
          AND c.excluded=0 AND c.deleted=0 AND c.withdrawn_at IS NULL
          AND (t.source_id IS NULL OR t.counter!=?)''', (session_id, self.counter)).fetchall()
        values = []
        for row in rows:
            source = json.loads(row['payload'])
            text = source['role'] + ': ' + source['text'] + '\n'
            values.append((row['id'], self.counter, self.core.tokens.count_text(text)))
        if values:
            with self.db:
                self.db.executemany('INSERT OR REPLACE INTO source_token_counts VALUES(?,?,?)', values)

    def status(self, session_id='default', *, retry_failed=True):
        session_id = self.core.consolidation.session(session_id)
        self._backfill(session_id)
        counts = self.db.execute('''
          SELECT COALESCE(SUM(t.tokens),0) pending_tokens,COUNT(*) pending_sources,
          COALESCE(SUM(CASE WHEN i.state='failed' THEN 1 ELSE 0 END),0) failed_sources,
          COALESCE(SUM(CASE WHEN i.state='working' THEN 1 ELSE 0 END),0) working_sources,
          COALESCE(SUM(CASE WHEN i.state='pending' OR
            (i.state='failed' AND ? AND i.attempts<?) THEN 1 ELSE 0 END),0) runnable_sources
          FROM inbox i JOIN controls c ON c.source_id=i.id
          JOIN source_token_counts t ON t.source_id=i.id AND t.counter=?
          WHERE i.session_id=? AND i.state NOT IN ('done','deleted','cancelled')
          AND c.excluded=0 AND c.deleted=0 AND c.withdrawn_at IS NULL''',
          (int(retry_failed), self.core.config.max_extract_attempts, self.counter, session_id)).fetchone()
        result = dict(counts)
        now = time.time()
        trigger = self.db.execute('SELECT * FROM extraction_triggers WHERE session_id=?', (session_id,)).fetchone()
        continuation = bool(trigger and trigger['continuation'] and result['pending_sources'])
        due = result['pending_tokens'] >= self.core.config.extraction_threshold_tokens or continuation
        enabled = self.core.config.extraction_mode == 'token_threshold'
        if not enabled:
            state = 'disabled'
        elif result['working_sources'] or (trigger and trigger['lease_until'] > now):
            state = 'busy'
        elif not due:
            state = 'below_threshold'
        elif not result['runnable_sources']:
            state = 'blocked'
        elif trigger and trigger['retry_after'] > now:
            state = 'cooldown'
        else:
            state = 'due'
        result.update(session_id=session_id, state=state, enabled=enabled,
                      threshold_tokens=self.core.config.extraction_threshold_tokens,
                      token_counter=self.counter, estimated=True, native_usage=False,
                      count_scope='sum of role: text newline for visible unfinished sources',
                      continuation_required=continuation,
                      retry_after=trigger['retry_after'] if trigger else 0,
                      execution='bounded_batches', single_256k_inference=False)
        return result

    def settle(self, session_id):
        # An earlier event may finish a previously partial threshold job.
        # Do not let that old continuation trigger the next tiny conversation.
        with self.db:
            self.db.execute('''UPDATE extraction_triggers SET continuation=0,retry_after=0
              WHERE session_id=? AND NOT EXISTS(
                SELECT 1 FROM inbox i JOIN controls c ON c.source_id=i.id
                WHERE i.session_id=? AND i.state NOT IN ('done','deleted','cancelled')
                AND c.excluded=0 AND c.deleted=0 AND c.withdrawn_at IS NULL)''',
              (session_id, session_id))

    def run(self, session_id='default', *, retry_failed=True):
        before = self.status(session_id, retry_failed=retry_failed)
        # Avoid lease writes on every ordinary message below the threshold.
        if before['state'] == 'busy':
            self.core.consolidation._recover()
            before = self.status(session_id, retry_failed=retry_failed)
        if before['state'] != 'due':
            return dict(state=before['state'], dispatched=False, threshold=before)
        session_id = before['session_id']
        now = time.time()
        claim_id = 'threshold-' + uuid.uuid4().hex
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            previous = self.db.execute('SELECT * FROM extraction_triggers WHERE session_id=?', (session_id,)).fetchone()
            if previous and (previous['lease_until'] > now or previous['retry_after'] > now):
                return dict(state='busy', dispatched=False, threshold=before)
            if previous:
                self.db.execute('''UPDATE extraction_trigger_events SET state='expired',
                  finished_at=?,pending_tokens_after=? WHERE id=? AND state='running' ''',
                  (now, before['pending_tokens'], previous['claim_id']))
            # Persist the continuation BEFORE inference: a crash after some
            # commits must not strand the remainder below the threshold.
            self.db.execute('''INSERT INTO extraction_triggers(session_id,claim_id,lease_until,continuation)
              VALUES(?,?,?,1) ON CONFLICT(session_id) DO UPDATE SET
              claim_id=excluded.claim_id,lease_until=excluded.lease_until,continuation=1''',
              (session_id, claim_id, now + 300))
            self.db.execute('''INSERT INTO extraction_trigger_events
              (id,session_id,started_at,threshold_tokens,pending_tokens_before,state)
              VALUES(?,?,?,?,?,'running')''',
              (claim_id, session_id, now, before['threshold_tokens'], before['pending_tokens']))
        error = None
        try:
            outcome = self.core._finalize_session(session_id, 'token_threshold', retry_failed)
        except Exception as exc:
            error = type(exc).__name__
            outcome = dict(event='token_threshold', session_id=session_id, complete=False,
                           error=error, raw_retained=True)
        after = self.status(session_id, retry_failed=retry_failed)
        remaining = bool(after['pending_sources'])
        state = 'failed' if error else 'complete' if outcome['complete'] else 'incomplete'
        finished = time.time()
        with self.db:
            self.db.execute('''UPDATE extraction_triggers SET lease_until=0,
              retry_after=?,continuation=? WHERE session_id=? AND claim_id=?''',
              (finished + self.core.config.extraction_retry_seconds if remaining else 0,
               int(remaining), session_id, claim_id))
            self.db.execute('''UPDATE extraction_trigger_events SET finished_at=?,
              pending_tokens_after=?,state=?,model_calls=?,error=? WHERE id=?''',
              (finished, after['pending_tokens'], state, outcome.get('model_calls'), error, claim_id))
        return dict(state=state, dispatched=True, trigger_id=claim_id, processing=outcome,
                    before=before, threshold=self.status(session_id, retry_failed=retry_failed))
