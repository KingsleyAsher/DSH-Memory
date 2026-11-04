"""Plugin scope ownership and durable global evidence archives; no model calls."""
import json
import time
import uuid
import re
from .atomic_wire import segments
from .contract import sha

GLOBAL_PROJECT='@memory/global'


class PluginScopes:
    def __init__(self,bridge):
        self.bridge=bridge;self.core=bridge.core;self.db=bridge.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS plugin_windows(window_id TEXT PRIMARY KEY,project TEXT,scope_key TEXT);
        CREATE TABLE IF NOT EXISTS plugin_session_scopes(session_id TEXT PRIMARY KEY,scope_key TEXT,retired INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS plugin_erased_messages(session_id TEXT,message_id TEXT,PRIMARY KEY(session_id,message_id));
        CREATE TABLE IF NOT EXISTS plugin_context_labels(scope_key TEXT PRIMARY KEY,project TEXT);
        CREATE TABLE IF NOT EXISTS plugin_memory_candidates(id TEXT PRIMARY KEY,project TEXT,scope TEXT,title TEXT,body TEXT,quote TEXT,reason TEXT,confidence REAL,state TEXT DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS plugin_memory_entries(
          id TEXT PRIMARY KEY,source_id TEXT,claim_id TEXT UNIQUE,scope TEXT,project TEXT,title TEXT,
          body TEXT,quote TEXT,proofs TEXT,origin TEXT,detached INTEGER DEFAULT 0,deleted INTEGER DEFAULT 0,created REAL);
        ''')
        if 'metadata' not in {r[1] for r in self.db.execute('PRAGMA table_info(plugin_memory_entries)')}:
            with self.db:self.db.execute("ALTER TABLE plugin_memory_entries ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")

    def shared_project_key(self, project):
        normalized=project.replace('\\','/').rstrip('/').casefold()
        # Reuse previously installed project scopes; never orphan old entries.
        for row in self.db.execute('SELECT scope_key,project FROM plugin_context_labels ORDER BY rowid'):
            if row['project'].replace('\\','/').rstrip('/').casefold()==normalized:
                if self.db.execute('SELECT 1 FROM plugin_session_scopes WHERE scope_key=? AND retired=1',(row['scope_key'],)).fetchone():continue
                return row['scope_key']
        return 'project:'+sha('workspace\0'+normalized)[:32]

    def project_for(self,session,fallback):
        row=self.db.execute('SELECT * FROM plugin_session_scopes WHERE session_id=?',(session,)).fetchone()
        if row:
            if row['retired']:raise ValueError('project_session_retired')
            return row['scope_key']
        if session:
            key=self.shared_project_key(fallback)
            with self.db:
                self.db.execute('INSERT INTO plugin_session_scopes VALUES(?,?,0)',(session,key))
                self.db.execute('INSERT OR IGNORE INTO plugin_context_labels VALUES(?,?)',(key,fallback))
            return key
        return fallback

    def project_keys(self,key):
        """Older builds assigned a new key per window; share their same-project notes.

        Keep immutable proof scopes unchanged. Retired/explicitly cleared scopes
        remain excluded and another project's entries are never included.
        """
        if not key:return []
        label=self.db.execute('SELECT project FROM plugin_context_labels WHERE scope_key=?',(key,)).fetchone()
        if not label:return [key]
        normalized=label[0].replace('\\','/').rstrip('/').casefold()
        return [r['scope_key'] for r in self.db.execute('SELECT * FROM plugin_context_labels')
                if r['project'].replace('\\','/').rstrip('/').casefold()==normalized and
                not self.db.execute('SELECT 1 FROM plugin_session_scopes WHERE scope_key=? AND retired=1',(r['scope_key'],)).fetchone()]

    def sync_entries(self):
        """Archive only already-admitted assertions and their minimal proofs.

        A global archive owns its immutable citation independently of a later
        project purge; it never points a reader at a deleted original message.
        """
        facts=self.core.store.facts(10**12)
        records=[dict(f,record_kind='fact') for f in facts]
        for point in self.core.store._linked_records(10**12):
            records.append(dict(point,value_text=point['point']['statement'],quote='\n'.join(e['quote'] for e in point['point']['evidence']),record_kind='linked'))
        for record in records:
            meta=self.db.execute('SELECT * FROM memory_claims WHERE id=?',(record['id'],)).fetchone()
            if not meta:continue
            scope='global' if meta['lifetime']=='global' else 'project'
            proofs=record.get('point',{}).get('evidence') or [dict(source_id=record['source_id'],quote=record['value_text'])]
            # Archive proofs contain only this assertion's evidence, never a
            # second full project transcript hidden in global memory.
            with self.db:
                self.db.execute('''INSERT OR IGNORE INTO plugin_memory_entries
                  (id,source_id,claim_id,scope,project,title,body,quote,proofs,origin,detached,deleted,created,metadata)
                  VALUES(?,?,?,?,?,?,?,?,?,?,0,0,?,?)''',('memory-'+record['id'],record['source_id'],record['id'],scope,
                  record['project'],meta['attribute'],record['value_text'],record['value_text'] if record['record_kind']=='fact' else record['quote'],
                  json.dumps(proofs,ensure_ascii=False),'automatic',time.time(),json.dumps({k:record[k] for k in ['epistemic','kind','field','record_kind'] if k in record},ensure_ascii=False)))
        # Explicit replacement/retraction retires an attached archive. Purged
        # global archives are detached deliberately and retain their evidence.
        active={r['id'] for r in records}
        with self.db:
            for row in self.db.execute('SELECT id,claim_id FROM plugin_memory_entries WHERE detached=0 AND deleted=0').fetchall():
                if row['claim_id'] not in active:self.db.execute('UPDATE plugin_memory_entries SET deleted=1 WHERE id=?',(row['id'],))

    def clear_project(self,scope_key):
        return sum(self._clear_scope(key) for key in self.project_keys(scope_key))

    def _clear_scope(self,scope_key):
        if not scope_key or scope_key==GLOBAL_PROJECT:return 0
        with self.db:self.db.execute('DELETE FROM plugin_memory_candidates WHERE project=?',(scope_key,))
        self.sync_entries()
        rows=self.db.execute("SELECT id,payload,session_id FROM inbox WHERE json_extract(payload,'$.project')=? AND state!='deleted'",(scope_key,)).fetchall()
        with self.db:
            self.db.execute("UPDATE plugin_memory_entries SET detached=1 WHERE project=? AND scope='global'",(scope_key,))
            self.db.execute("DELETE FROM plugin_memory_entries WHERE project=? AND scope='project'",(scope_key,))
            self.db.execute('UPDATE plugin_session_scopes SET retired=1 WHERE scope_key=?',(scope_key,))
            for row in rows:
                host=self.db.execute('SELECT session_id,message_id FROM plugin_sources WHERE id=?',(row['id'],)).fetchone()
                if host:self.db.execute('INSERT OR IGNORE INTO plugin_erased_messages VALUES(?,?)',tuple(host))
        for row in rows:self.core.delete(row['id'])
        return len(rows)

    def activate(self,window_id,project,session_id=None,clear=False):
        if not isinstance(window_id,str) or not 1<=len(window_id)<=120:raise ValueError('invalid_window')
        if project is not None and (not isinstance(project,str) or not project.strip() or len(project)>2000):raise ValueError('invalid_project')
        old=self.db.execute('SELECT * FROM plugin_windows WHERE window_id=?',(window_id,)).fetchone()
        changed=bool(old and (old['project']!=project or clear))
        removed=self.clear_project(old['scope_key']) if old and clear else 0
        key=old['scope_key'] if old and not changed else (('project:'+uuid.uuid4().hex if clear else self.shared_project_key(project)) if project else None)
        # A first turn can be admitted just before the UI's activation arrives.
        # Adopt its provisional scope instead of silently orphaning that turn.
        if not old and session_id and project:
            provisional=self.db.execute('''SELECT s.scope_key FROM plugin_session_scopes s JOIN plugin_context_labels l USING(scope_key)
              WHERE s.session_id=? AND s.retired=0 AND l.project=? AND NOT EXISTS(
              SELECT 1 FROM plugin_windows w WHERE w.scope_key=s.scope_key)''',(session_id,project)).fetchone()
            if provisional:key=provisional[0]
        with self.db:
            if key:self.db.execute('INSERT OR IGNORE INTO plugin_context_labels VALUES(?,?)',(key,project))
            self.db.execute('INSERT INTO plugin_windows VALUES(?,?,?) ON CONFLICT(window_id) DO UPDATE SET project=excluded.project,scope_key=excluded.scope_key',(window_id,project,key))
            if session_id and key:self.db.execute('INSERT INTO plugin_session_scopes VALUES(?,?,0) ON CONFLICT(session_id) DO UPDATE SET scope_key=excluded.scope_key,retired=0',(session_id,key))
        return dict(project=project,scope_key=key,cleared_sources=removed)

    def window(self,window_id):
        row=self.db.execute('SELECT * FROM plugin_windows WHERE window_id=?',(window_id,)).fetchone()
        return dict(row) if row else dict(window_id=window_id,project=None,scope_key=None)

    def capture_explicit(self,session,project,text,source_id):
        """Preserve a short explicit user instruction verbatim; no inferred facts."""
        if not isinstance(text,str) or len(text)>600:return False
        if re.search(r'不要记|不用记|别记|不必记|例如|比如|他[说讲]|她[说讲]|是否|能否|[?？]',text):return False
        if not (re.search(r'请?记住|记下来|记一下',text) or re.search(r'以后(?:我的|所有的?|每次).{1,120}(都要|一律|默认|就要|要做成)',text,re.S)):return False
        # Bind to the real user message, not a second synthetic manual source.
        scope='global' if re.search(r'以后(?:我的|所有的?|每次)',text) and not re.search(r'本项目|这个项目|当前项目|本次|这次',text) else 'project'
        parts=segments(dict(text=text))
        if not 1<=len(parts)<=16:return False
        item=dict(id=source_id,f=[dict(v=p['text'],e=[i+1],a=text[:50],t='',f='rule',l=scope) for i,p in enumerate(parts)],
                  o=[dict(op='assert',n='F'+str(i)) for i in range(len(parts))])
        result=self.bridge.flow.tools.write('explicit-'+sha(source_id+'\0'+text)[:32],item,reviewed=True)
        self.sync_entries()
        entries=self.db.execute('''SELECT e.id FROM plugin_memory_entries e JOIN memory_claims m ON m.id=e.claim_id
          WHERE e.source_id=? ORDER BY m.ordinal''',(source_id,)).fetchall()
        if entries:
            with self.db:
                self.db.execute("UPDATE plugin_memory_entries SET origin='explicit',deleted=1 WHERE source_id=?",(source_id,))
                self.db.execute("UPDATE plugin_memory_entries SET deleted=0,title=?,body=?,quote=? WHERE id=?",(text[:50],text,text,entries[0]['id']))
        return result.get('state')=='saved'

    def suggest(self,session,title,text,quote,reason,confidence,scope='project'):
        if scope not in ('global','project') or not isinstance(confidence,(float,int)) or not 0<=confidence<=0.35:raise ValueError('only_very_low_confidence_candidates')
        if not all(isinstance(v,str) and v.strip() for v in (title,text,quote,reason)) or len(text)>4000 or len(title)>80 or len(reason)>500:raise ValueError('invalid_candidate')
        context=self.db.execute('SELECT * FROM plugin_session_scopes WHERE session_id=? AND retired=0',(session,)).fetchone()
        if not context:raise ValueError('inactive_candidate_session')
        sources=[json.loads(r['payload']) for r in self.db.execute('SELECT i.id,i.payload FROM inbox i JOIN plugin_sources p ON p.id=i.id WHERE p.session_id=? AND p.role=?',(session,'user')) if self.core.store.visible_source(r['id'])]
        if not any(s and quote in s['text'] for s in sources):raise ValueError('candidate_quote_requires_user_source')
        project=context['scope_key'];ident='candidate-'+sha(session+'\0'+text+'\0'+quote)[:32]
        with self.db:self.db.execute('INSERT OR IGNORE INTO plugin_memory_candidates(id,project,scope,title,body,quote,reason,confidence) VALUES(?,?,?,?,?,?,?,?)',(ident,project,scope,title,text,quote,reason,confidence))
        return dict(state='pending_user_review',candidate_id=ident,recall_enabled=False)

    def candidates(self,window_id):
        context=self.window(window_id)
        return dict(candidates=[dict(r) for r in self.db.execute("SELECT * FROM plugin_memory_candidates WHERE project=? AND state='pending'",(context['scope_key'],))])

    def resolve_candidate(self,window_id,candidate_id,accept=False,text=None):
        context=self.window(window_id)
        row=self.db.execute("SELECT * FROM plugin_memory_candidates WHERE id=? AND project=? AND state='pending'",(candidate_id,context['scope_key'])).fetchone()
        if not row:raise ValueError('candidate_not_in_current_project')
        if accept:self.add(window_id,row['scope'],text if text is not None else row['body'],row['title'],request_id=candidate_id)
        with self.db:self.db.execute('UPDATE plugin_memory_candidates SET state=? WHERE id=?',('accepted' if accept else 'rejected',candidate_id))
        return self.candidates(window_id)

    def add(self,window_id,scope,text,title='',request_id=None):
        if scope not in ['global','project']:raise ValueError('invalid_memory_scope')
        if not isinstance(text,str) or not text.strip() or len(text)>4000:raise ValueError('memory_text_1_to_4000')
        if not isinstance(title,str) or len(title)>80:raise ValueError('memory_title_max_80')
        context=self.window(window_id);project=GLOBAL_PROJECT if scope=='global' else context['scope_key']
        if not project:raise ValueError('no_active_project')
        text=text.strip();title=(title.strip() or text[:24])[:75]
        request_id=request_id or uuid.uuid4().hex
        if not isinstance(request_id,str) or not 1<=len(request_id)<=100:raise ValueError('invalid_request_id')
        sid='manual-'+sha(window_id+'\0'+request_id)[:32]
        existing=self.db.execute('SELECT payload FROM inbox WHERE id=?',(sid,)).fetchone()
        if existing:
            original=json.loads(existing['payload'])
            if original['text']!=text or original['project']!=project:raise ValueError('manual_request_changed')
            return dict(state='saved',entries=self.list(window_id)['entries'])
        source=dict(id=sid,session_id='manual:'+window_id,project=project,entity='workspace',role='user',text=text)
        parts=segments(source)
        if len(parts)>16 or any(len(p['text'])>800 for p in parts):raise ValueError('memory_point_too_long_split_into_shorter_sentences')
        self.bridge.flow.ingest(source)
        item=dict(id=sid,f=[dict(v=p['text'],e=[i+1],a=title+('·'+str(i+1) if len(parts)>1 else ''),t='',f='other',l=scope) for i,p in enumerate(parts)],
                  o=[dict(op='assert',n='F'+str(i)) for i in range(len(parts))])
        result=self.bridge.flow.tools.write('manual:'+request_id,item,reviewed=True)
        if result['state']!='saved':raise ValueError('manual_memory_not_saved')
        self.sync_entries()
        # One user submission is one editable card, even when the core stores
        # several sentence-level assertions underneath it.
        entries=self.db.execute('''SELECT e.id FROM plugin_memory_entries e JOIN memory_claims m ON m.id=e.claim_id
          WHERE e.source_id=? ORDER BY m.ordinal''',(sid,)).fetchall()
        with self.db:
            self.db.execute("UPDATE plugin_memory_entries SET origin='manual',deleted=1 WHERE source_id=?",(sid,))
            self.db.execute('''UPDATE plugin_memory_entries SET deleted=0,title=?,body=?,quote=?,proofs=? WHERE id=?''',
                (title,text,text,json.dumps([dict(source_id=sid,quote=text)],ensure_ascii=False),entries[0]['id']))
        return dict(state='saved',entries=self.list(window_id)['entries'])

    def list(self,window_id):
        self.sync_entries();context=self.window(window_id)
        keys=self.project_keys(context['scope_key'])
        rows=self.db.execute("SELECT * FROM plugin_memory_entries WHERE deleted=0 ORDER BY created DESC").fetchall()
        rows=[r for r in rows if r['scope']=='global' or r['project'] in keys]
        return dict(project=context['project'],entries=[dict(id=r['id'],scope=r['scope'],project=r['project'],title=r['title'],text=r['body'],origin=r['origin'],created=r['created'],quote=r['quote'],proofs=json.loads(r['proofs']),metadata=json.loads(r['metadata'])) for r in rows])

    def remove(self,window_id,entry_id):
        context=self.window(window_id)
        row=self.db.execute('SELECT * FROM plugin_memory_entries WHERE id=? AND deleted=0',(entry_id,)).fetchone()
        if not row or row['scope']!='global' and row['project'] not in self.project_keys(context['scope_key']):raise ValueError('memory_not_in_current_scope')
        # A tombstone prevents automatic re-archiving from the same old claim.
        with self.db:self.db.execute("UPDATE plugin_memory_entries SET deleted=1,body='',quote='',proofs='[]' WHERE id=?",(entry_id,))
        if row['origin'] in ('manual','explicit'):self.core.delete(row['source_id'])
        return dict(state='deleted')

    def evidence(self,project,question):
        self.sync_entries()
        keys=self.project_keys(project)
        rows=[r for r in self.db.execute("SELECT * FROM plugin_memory_entries WHERE deleted=0 ORDER BY created DESC")
              if r['scope']=='global' or r['project'] in keys]
        project_titles={r['title'] for r in rows if r['scope']=='project'}
        # Explicitly saved notes are bounded standing context. They do not all
        # enter an ever-growing prompt: share the core's final token budget.
        scored=[]
        query=set(question.lower())
        for r in rows:
            if r['scope']=='global' and r['title'] in project_titles:continue
            pieces=[r['body']] if r['origin']!='manual' or len(r['body'])<=700 else [p['text'] for p in segments(dict(text=r['body']))]
            for piece in pieces:
                score=len(query & set((r['title']+piece).lower()))
                scored.append((score,1 if r['scope']=='project' else 0,r['created'],r,piece))
        return [dict(source_id=r['id'],value=piece,quote=piece if r['origin']=='manual' else r['quote'],scope=r['scope'],origin=r['origin'],title=r['title'],source_project=r['project'],applicable_here=r['scope']=='global' or r['project'] in keys,
                     archived=True,**json.loads(r['metadata'])) for _,_,_,r,piece in sorted(scored,key=lambda v:v[:3],reverse=True)]
