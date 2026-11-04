"""Per-fact acceptance, immutable sources and program-owned correction edges."""
import json
import re
import sqlite3

from .contract import normalize, sha, validate_fact
from .state import mutations


def explicit_update(fact, text):
    quote = fact['quote']
    if fact['field'] in ['reminder_time','archive_path','service_port','contact_phone'] and fact['kind']=='fact':
        if fact['epistemic']=='planned':return False
        return mutations(text).get(fact['field'])=='set' or normalize(fact['field'],fact['value_text'])=='__unset__'
    if fact['field'] == 'deployment_state' and re.search(r'已(?:经)?.*(?:部署|上线)|完成.*验收', quote):
        return True
    if fact['field'].startswith('incident_'):
        explicit=bool(re.search(r'更正|改为|修正|此前.*不对|之前.*不对',quote))
        positives=list(re.finditer(r'查明(?:原因|根因)|(?:原因|根因)(?:是|为)|确认.{0,6}(?:原因|根因)',quote))
        positive=any(not re.search(r'未|没|不确定|怀疑|猜测|推测',quote[max(0,m.start()-6):m.start()]) for m in positives)
        return explicit or (fact['epistemic']=='stated' and positive)
    # Empty-topic prose is not a shared property slot. Attribute-aware updates
    # must use explicit claim IDs through finish_atomic instead.
    if fact['field'] in ['other','preference']:
        return False
    return bool(re.search(r'改(?:成|到|为|用)|更正|调整(?:为|到)|换成|换到|以.+为准|从现在|不再|撤销|取消|暂停|停止', quote))


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,seq INTEGER UNIQUE,project TEXT,entity TEXT,role TEXT,text TEXT,sha TEXT,state TEXT,error TEXT,proposal TEXT);
        CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY,source_id TEXT,seq INTEGER,project TEXT,entity TEXT,field TEXT,topic TEXT,kind TEXT,epistemic TEXT,value TEXT,value_text TEXT,quote TEXT,valid_to INTEGER,superseded_by TEXT);
        CREATE TABLE IF NOT EXISTS views(id TEXT PRIMARY KEY,source_id TEXT,quote TEXT,purpose TEXT,fact_ids TEXT);
        CREATE TABLE IF NOT EXISTS audit(source_id TEXT,item INTEGER,event TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS pending_updates(source_id TEXT,seq INTEGER,project TEXT,entity TEXT,field TEXT,resolved_at INTEGER);
        ''')

    def facts(self, at=None):
        rows = [dict(r) for r in self.db.execute('SELECT * FROM facts ORDER BY seq,id')]
        return rows if at is None else [r for r in rows if r['seq'] <= at and (r['valid_to'] is None or r['valid_to'] > at)]

    def prior(self, project, entity):
        return [{k: r[k] for k in ['field', 'topic', 'kind', 'epistemic', 'value', 'quote']}
                for r in self.facts(10**12) if (r['project'], r['entity']) == (project, entity)]

    def ingest(self, source, extraction):
        old = self.db.execute('SELECT sha,state FROM sources WHERE id=?', (source['id'],)).fetchone()
        if old:
            if old['sha'] != sha(source['text']):
                raise ValueError('source_id_changed')
            return old['state']
        facts = extraction.get('facts', []) if source['role'] in ['user', 'tool'] else []
        accepted, rejected = [], list(extraction.get('diagnostics', []))
        for f in facts:
            try:
                validate_fact(source['text'], f)
                accepted.append(f)
            except (ValueError, TypeError, KeyError) as exc:
                rejected.append({'reason': str(exc), 'fact': f})
        state = 'partial' if rejected and accepted else 'parked' if rejected else 'accepted'
        active = self.slot_facts(source,accepted) if hasattr(self,'slot_facts') else self.facts(source['seq'] - 1)
        with self.db:
            self.db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                (source['id'], source['seq'], source['project'], source['entity'], source['role'], source['text'], sha(source['text']), state,
                 json.dumps(rejected, ensure_ascii=False) if rejected else None,
                 json.dumps({'facts': accepted, 'missing_fields': extraction.get('missing_fields', []),
                             'linked_points':extraction.get('linked_points',[]),
                             'deferred_points':extraction.get('deferred_points',[]),
                             'admission_review':extraction.get('admission_review',{})}, ensure_ascii=False)))
            for i, f in enumerate(accepted):
                fid = sha(source['id'] + ':' + str(i))[:20]
                key = (source['project'], source['entity'], f['field'], f['topic'], f['kind'])
                targets = [r for r in active if (r['project'], r['entity'], r['field'], r['topic'], r['kind']) == key]
                update = explicit_update(f, source['text'])
                semantic_action=extraction.get('semantic_actions',{}).get(f['field'])
                if f['field'] in ['reminder_time','archive_path','service_port','contact_phone'] and f['kind']=='fact' and semantic_action:
                    update=semantic_action=='set' and f['epistemic']!='planned'
                self.db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (fid, source['id'], source['seq'], source['project'], source['entity'], f['field'], f['topic'], f['kind'], f['epistemic'], normalize(f['field'], f['value_text']), f['value_text'], f['quote'], None, None))
                if update:
                    for target in targets:
                        self.db.execute('UPDATE facts SET valid_to=?,superseded_by=? WHERE id=?', (source['seq'], fid, target['id']))
                    if f['kind'] == 'fact':
                        self.db.execute('UPDATE pending_updates SET resolved_at=? WHERE project=? AND entity=? AND field=? AND resolved_at IS NULL', (source['seq'], source['project'], source['entity'], f['field']))
                self.db.execute('INSERT INTO audit VALUES(?,?,?,?)', (source['id'], i, 'replace' if update and targets else 'assert', json.dumps([r['id'] for r in targets] if update else [])))
            for i, item in enumerate(rejected):
                self.db.execute('INSERT INTO audit VALUES(?,?,?,?)', (source['id'], i, 'rejected_item', json.dumps(item, ensure_ascii=False)))
            for field in extraction.get('pending_fields', []) if source['role'] in ['user', 'tool'] else []:
                self.db.execute('INSERT INTO pending_updates VALUES(?,?,?,?,?,NULL)', (source['id'], source['seq'], source['project'], source['entity'], field))
            # Extra views are source-grounded incident facets, never required for acceptance.
            events = {}
            for r in self.db.execute('SELECT * FROM facts WHERE source_id=?', (source['id'],)):
                if r['field'].startswith('incident_'):
                    events.setdefault((r['topic'], r['kind']), []).append(dict(r))
            for group in events.values():
                if len({r['field'] for r in group}) > 1:
                    for r in group[:3]:
                        self.db.execute('INSERT INTO views VALUES(?,?,?,?,?)', (sha(r['id'] + ':view')[:20], source['id'], r['quote'], r['field'], json.dumps([r['id']])))
        return state

    def units(self, at, historical=False):
        if historical:
            first = {}
            for r in self.facts():
                if r['seq'] <= at:
                    first.setdefault((r['project'], r['entity'], r['field'], r['topic'], r['kind']), r)
            rows = list(first.values())
        else:
            rows = self.facts(at)
        groups = {}
        for r in rows:
            field = 'event:' + r['topic'] if r['field'].startswith('incident_') else r['field']
            key = (r['source_id'], r['kind'], field)
            unit = groups.setdefault(key, {'id': ':'.join(key), 'source_id': r['source_id'], 'seq': r['seq'], 'project': r['project'], 'entity': r['entity'], 'kind': r['kind'], 'facts': [], 'views': []})
            unit['facts'].append(r)
        for unit in groups.values():
            ids = {r['id'] for r in unit['facts']}
            for view in self.db.execute('SELECT * FROM views WHERE source_id=?', (unit['source_id'],)):
                if set(json.loads(view['fact_ids'])) <= ids:
                    unit['views'].append(dict(view))
        return list(groups.values())
