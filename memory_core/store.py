"""Persistent inbox, immutable sources, fact lifecycle and derived-cache ledger."""
import copy,json,re,time
from .store_base import Store as BaseStore
from .contract import sha,normalize
from .views import canonical_event,fingerprint,propose,digest
from .extraction_base import change_fields,anchors
from .contract import EXAMPLE
from .policy import SCOPED_FIELDS
from .state import mutations
from .identity import project_key,entity_key,event_key
from .claim_store import ClaimStore
from .reminders import is_event_reminder, reminder_label

def attempted_actual_fields(text):
    return {field for field,action in mutations(text).items() if action in ['set','pending']}

class Store(ClaimStore,BaseStore):
    def __init__(self,path):
        super().__init__(path)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,seq INTEGER UNIQUE,payload TEXT,sha TEXT,state TEXT,attempts INTEGER DEFAULT 0,lease_until REAL DEFAULT 0,error TEXT);
        CREATE TABLE IF NOT EXISTS controls(source_id TEXT PRIMARY KEY,excluded INTEGER DEFAULT 0,deleted INTEGER DEFAULT 0,withdrawn_at INTEGER);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER);
        INSERT OR IGNORE INTO meta VALUES('generation',0);
        CREATE TABLE IF NOT EXISTS derived(unit_id TEXT,view_no INTEGER,source_id TEXT,fingerprint TEXT,text_sha TEXT,text TEXT,purpose TEXT,fact_ids TEXT,PRIMARY KEY(unit_id,view_no));
        CREATE TABLE IF NOT EXISTS embeddings(model TEXT,dim INTEGER,text_sha TEXT,data BLOB,bytes_sha TEXT,PRIMARY KEY(model,dim,text_sha));
        CREATE TABLE IF NOT EXISTS model_cache(key TEXT PRIMARY KEY,source_id TEXT,response TEXT);
        CREATE TABLE IF NOT EXISTS events(project TEXT,entity TEXT,kind TEXT,event_key TEXT,label TEXT,PRIMARY KEY(project,entity,kind,event_key));
        CREATE TABLE IF NOT EXISTS index_state(text_sha TEXT PRIMARY KEY,attempts INTEGER DEFAULT 0,retry_after REAL DEFAULT 0,error TEXT);
        CREATE TABLE IF NOT EXISTS scope_keys(project TEXT,entity TEXT,project_id TEXT,entity_id TEXT,PRIMARY KEY(project,entity),UNIQUE(project_id,entity_id));
        CREATE TABLE IF NOT EXISTS source_reviews(source_id TEXT PRIMARY KEY,actions TEXT,review TEXT);
        CREATE INDEX IF NOT EXISTS facts_scope ON facts(project,entity,seq);
        CREATE INDEX IF NOT EXISTS facts_slot ON facts(project,entity,field,topic,kind,valid_to);
        ''')
        if 'session_id' not in {r['name'] for r in self.db.execute('PRAGMA table_info(inbox)')}:
            self.db.execute("ALTER TABLE inbox ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'")
        self.db.execute('CREATE INDEX IF NOT EXISTS inbox_session ON inbox(session_id,state,seq)')
        # Idempotent migration: stable names retain the same IDs after restart.
        for r in self.db.execute('SELECT DISTINCT project,entity FROM sources').fetchall():self.register_scope(r['project'],r['entity'])
        for r in self.db.execute("SELECT payload FROM inbox WHERE state!='deleted'").fetchall():
            s=json.loads(r['payload']);self.register_scope(s['project'],s['entity'],s.get('project_id'),s.get('entity_id'))
        self._init_claim_store()
        self.db.commit()
    def register_scope(self,project,entity,project_id=None,entity_id=None):
        old=self.db.execute('SELECT * FROM scope_keys WHERE project=? AND entity=?',(project,entity)).fetchone()
        if old:
            if (project_id and old['project_id']!=project_id) or (entity_id and old['entity_id']!=entity_id):raise ValueError('scope id changed')
            return dict(old)
        pid=project_id or project_key(project);eid=entity_id or entity_key(pid,entity)
        if any(not isinstance(x,str) or not x or len(x)>160 for x in [pid,eid]):raise ValueError('invalid scope id')
        if self.db.execute('SELECT 1 FROM scope_keys WHERE (project_id=? AND project!=?) OR (entity_id=? AND (project!=? OR entity!=?))',(pid,project,eid,project,entity)).fetchone():raise ValueError('scope id collision')
        self.db.execute('INSERT INTO scope_keys VALUES(?,?,?,?)',(project,entity,pid,eid));return dict(project=project,entity=entity,project_id=pid,entity_id=eid)
    def generation(self):return self.db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0]
    def bump(self):self.db.execute("UPDATE meta SET value=value+1 WHERE key='generation'")
    def next_seq(self):return self.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM inbox').fetchone()[0]
    def enqueue(self,source):
        source=copy.deepcopy(source)
        required=['id','project','entity','role','text']
        if any(not isinstance(source.get(k),str) or not source[k] for k in required):raise ValueError('invalid source')
        if source['role'] not in ['user','assistant','tool']:raise ValueError('invalid role')
        source.setdefault('session_id','default')
        if not isinstance(source['session_id'],str) or not source['session_id'] or len(source['session_id'])>160:raise ValueError('invalid session id')
        scope=self.register_scope(source['project'],source['entity'],source.get('project_id'),source.get('entity_id'))
        source.update(project_id=scope['project_id'],entity_id=scope['entity_id'])
        old=self.db.execute('SELECT * FROM inbox WHERE id=?',(source['id'],)).fetchone()
        if old:
            if old['state']=='deleted':raise ValueError('deleted source id cannot be reused')
            if old['sha']!=sha(source['text']):raise ValueError('immutable source; use revise')
            previous=json.loads(old['payload'])
            if any(previous[k]!=source[k] for k in ['project','entity','role']) or previous.get('session_id','default')!=source['session_id']:raise ValueError('source identity changed')
            return dict(old)
        source['seq']=source.get('seq') or self.next_seq()
        with self.db:
            self.db.execute('INSERT INTO inbox(id,seq,payload,sha,state,session_id) VALUES(?,?,?,?,?,?)',(source['id'],source['seq'],json.dumps(source,ensure_ascii=False),sha(source['text']),'pending',source['session_id']))
            self.db.execute('INSERT INTO controls(source_id) VALUES(?)',(source['id'],))
            if source['role'] in ['user','tool']:
                for field in attempted_actual_fields(source['text']):self.db.execute('INSERT INTO pending_updates VALUES(?,?,?,?,?,NULL)',(source['id'],source['seq'],source['project'],source['entity'],field))
            self._mark_pending_retractions(source)
            self._mark_pending_reminders(source)
            self.bump()
        return dict(self.db.execute('SELECT * FROM inbox WHERE id=?',(source['id'],)).fetchone())
    def claim_job(self):
        now=time.time()
        with self.db:
            self.db.execute("UPDATE inbox SET state='pending' WHERE state='working' AND lease_until<?",(now,))
            row=self.db.execute("SELECT * FROM inbox WHERE state='pending' ORDER BY seq LIMIT 1").fetchone()
            if not row:return None
            self.db.execute("UPDATE inbox SET state='working',attempts=attempts+1,lease_until=? WHERE id=?",(now+300,row['id']))
        return json.loads(row['payload'])
    def finish(self,source,result,*,linked_context=None):
        from .contextual import validate_point
        linked=[]
        for p in result.get('linked_points',[]):
            try:linked.append(validate_point(p,source,self.recent_dialogue(source) if linked_context is None else linked_context))
            except (ValueError,TypeError,KeyError) as exc:
                result.setdefault('diagnostics',[]).append(dict(reason=str(exc)))
        result={**result,'linked_points':linked}
        facts=[]
        actions=result.get('semantic_actions',mutations(source['text']))
        specific={canonical_event(f['topic']) for f in result.get('facts',[]) if f['field'] in SCOPED_FIELDS and len(canonical_event(f['topic']))>2}
        for f in result.get('facts',[]):
            f=copy.deepcopy(f)
            if f['kind']=='fact' and actions.get(f['field'])=='pending' and normalize(f['field'],f['value_text'])!='__unset__':continue
            if f['field'] in SCOPED_FIELDS:
                f['topic']=canonical_event(f['topic'])
                if len(f['topic'])<=2:
                    choices=[e for e in specific if e in f['quote']]
                    if len(choices)==1:f['topic']=choices[0]
                    elif len(choices)>1:continue  # Ambiguous generic fallback is not a third event.
                self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)',(source['project'],source['entity'],f['kind'],f['topic'],f['topic']))
            if not any(g['field']==f['field'] and g['topic']==f['topic'] and g['kind']==f['kind'] and g['epistemic']==f['epistemic'] and normalize(g['field'],g['value_text'])==normalize(f['field'],f['value_text']) for g in facts):facts.append(f)
        pending={field for field,action in actions.items() if action=='pending'} | ({field for field,action in actions.items() if action=='set'}-{f['field'] for f in facts if f['kind']=='fact'})
        result={**result,'facts':facts,'pending_fields':sorted(pending)}
        self.db.execute('DELETE FROM pending_updates WHERE source_id=?',(source['id'],))
        state=super().ingest(source,result)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO source_reviews VALUES(?,?,?)',(source['id'],json.dumps(actions),json.dumps(result.get('semantic_review',{}),ensure_ascii=False)))
            for fid in result.get('retract_ids',[]):
                target=self.db.execute('SELECT * FROM facts WHERE id=? AND project=? AND entity=? AND seq<? AND epistemic=?',(fid,source['project'],source['entity'],source['seq'],'hypothesis')).fetchone()
                if target and (target['valid_to'] is None or target['valid_to']>source['seq']):
                    self._invalidate_claim(fid,source['seq'],'retract:'+source['id'])
                    self.db.execute('INSERT INTO audit VALUES(?,?,?,?)',(source['id'],0,'retract_hypothesis',json.dumps([fid])))
            # Legacy ingestion reports the exact corrected IDs; synchronize only
            # those edges and this source's missing metadata, never scan the library.
            for audit in self.db.execute("SELECT detail FROM audit WHERE source_id=? AND event='replace'",(source['id'],)).fetchall():
                for fid in json.loads(audit['detail']):
                    target=self.db.execute('SELECT valid_to,superseded_by FROM facts WHERE id=?',(fid,)).fetchone()
                    if target and target['valid_to'] is not None:self._invalidate_claim(fid,target['valid_to'],target['superseded_by'])
            self._migrate_claim_metadata(source['id'])
            self.db.execute('DELETE FROM pending_claim_changes WHERE source_id=?',(source['id'],))
            self.db.execute("UPDATE inbox SET state='done',lease_until=0,error=NULL WHERE id=?",(source['id'],));self.bump()
        return state
    def fail(self,source,error):
        with self.db:self.db.execute("UPDATE inbox SET state='failed',lease_until=0,error=? WHERE id=?",(str(error)[:300],source['id']))
    def retry_failed(self,limit=2):
        with self.db:self.db.execute("UPDATE inbox SET state='pending',error=NULL WHERE state='failed' AND attempts<?",(limit,))
    def scoped_facts(self,at=None,project=None,entity=None,earliest=False,keys=None,include_pending=False):
        sql='SELECT f.* FROM facts f LEFT JOIN controls c ON c.source_id=f.source_id WHERE COALESCE(c.excluded,0)=0 AND COALESCE(c.deleted,0)=0';args=[]
        if at is not None:
            sql+=' AND f.seq<=?';args.append(at)
            if not earliest:
                sql+=' AND (f.valid_to IS NULL OR f.valid_to>?) AND (c.withdrawn_at IS NULL OR c.withdrawn_at>?)';args.extend([at,at])
        if project is not None:sql+=' AND f.project=?';args.append(project)
        if entity is not None:sql+=' AND f.entity=?';args.append(entity)
        if keys is not None:
            if not keys:return []
            sql+=' AND ('+' OR '.join('(f.field=? AND f.topic=? AND f.kind=?)' for _ in keys)+')'
            for key in keys:args.extend(key)
        sql+=' ORDER BY f.seq,f.id'
        rows=[dict(r) for r in self.db.execute(sql,args)]
        if at is not None and not earliest and not include_pending:
            blocked=self._pending_claim_ids(at);rows=[r for r in rows if r['id'] not in blocked]
        scopes={(r['project'],r['entity']):dict(r) for r in self.db.execute('SELECT * FROM scope_keys')}
        for r in rows:
            scope=scopes[(r['project'],r['entity'])];r.update(project_id=scope['project_id'],entity_id=scope['entity_id'])
            r['event_id']=event_key(scope['entity_id'],canonical_event(r['topic']),r['kind']) if r['field'] in SCOPED_FIELDS else ''
            if is_event_reminder(r):
                r['reminder_event']=True
                r['event_id']=event_key(scope['entity_id'],reminder_label(r),r['kind'])
                if r['epistemic']=='unknown':r['control']=True
        return [typed for r in rows if (typed:=self._decorate_operation_claim(r,r['seq'] if earliest else at if at is not None else 10**12)) is not None]
    def facts(self,at=None):return self.scoped_facts(at)
    def slot_facts(self,source,accepted):
        return self.scoped_facts(source['seq']-1,source['project'],source['entity'],keys=sorted({(f['field'],f['topic'],f['kind']) for f in accepted}))
    def prior(self,project,entity):
        return [{k:f[k] for k in ['id','source_id','seq','field','topic','kind','epistemic','value','quote']} for f in self.scoped_facts(10**12,project,entity)]
    def recent_dialogue(self,source,limit=4,max_chars=1600):
        rows=self.db.execute('SELECT s.* FROM sources s JOIN controls c ON c.source_id=s.id JOIN inbox i ON i.id=s.id WHERE s.project=? AND s.entity=? AND s.seq<? AND i.session_id=? AND c.excluded=0 AND c.deleted=0 AND c.withdrawn_at IS NULL ORDER BY s.seq DESC LIMIT ?',
                             (source['project'],source['entity'],source['seq'],source.get('session_id','default'),limit)).fetchall()
        result=[];size=0
        for row in rows:
            if size+len(row['text'])>max_chars:break
            result.append({k:row[k] for k in ['id','seq','project','entity','role','text']});size+=len(row['text'])
        return list(reversed(result))
    def extracted_context_points(self):
        """Selected multi-source points; retrieval preserves their full proof."""
        return [dict(source_id=r['source_id'],project=r['project'],entity=r['entity'],**r['point']) for r in self._linked_records()]
    def units(self,at,historical=False,project=None,entity=None):
        facts=self.scoped_facts(at,project,entity,earliest=historical)
        linked=self._linked_records(at,project,entity,earliest=historical)
        for f in linked:
            scope=self.register_scope(f['project'],f['entity'])
            f.update(project_id=scope['project_id'],entity_id=scope['entity_id'])
            f.setdefault('event_id','')
        facts+=linked
        if not historical:
            from .operation_recall import operation_frames
            facts+=operation_frames(self,at,project,entity)
        if not historical:facts+=self.reminder_controls(at,project,entity)
        if not historical:facts=[f for f in facts if not (f['field'] in ['reminder_time','archive_path','service_port','contact_phone'] and f['epistemic']=='planned')]
        if historical:
            first={}
            for f in facts:first.setdefault((f['project'],f['entity'],f['field'],f['topic'],f['kind'],f.get('attribute','') if f.get('record_kind')=='linked' else '',f.get('property','') if f.get('category') else ''),f)
            facts=list(first.values())
        groups={}
        for f in facts:
            typed=bool(f.get('category') and f.get('event_id'))
            field='semantic:'+f['event_id']+':'+f['property'] if typed else 'linked:'+f['attribute'] if f.get('record_kind')=='linked' else 'event:'+f['topic'] if f['field'] in SCOPED_FIELDS else 'reminder:'+reminder_label(f) if f.get('reminder_event') else f['field'];key=(f['source_id'],f['kind'],field)
            u=groups.setdefault(key,dict(id=':'.join(key),source_id=f['source_id'],seq=f['seq'],project=f['project'],entity=f['entity'],project_id=f['project_id'],entity_id=f['entity_id'],event_id=f['event_id'],kind=f['kind'],event_key=f['topic'] if typed else reminder_label(f) if f.get('reminder_event') else canonical_event(f['topic']) if f['field'] in SCOPED_FIELDS else '',facts=[],views=[]));u['facts'].append(f)
        for u in groups.values():
            if any(g.get('record_kind')=='linked' for g in u['facts']):
                u['candidate_text']='；'.join(g['value_text']+' '+
                    (' '.join(e['quote'] for e in g['evidence']) if 'evidence' in g else g.get('quote',''))
                    for g in u['facts'])
        return list(groups.values())
    def visible_source(self,sid,at=None):
        c=self.db.execute('SELECT * FROM controls WHERE source_id=?',(sid,)).fetchone()
        return bool(c and not c['excluded'] and not c['deleted'] and (c['withdrawn_at'] is None or at is not None and c['withdrawn_at']>at))
    def _invalidate_operation_stages(self,sid,redact=False):
        # The operation engine registers every source/context/target proof of
        # its persisted stages. Legacy databases have no such work to cancel.
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='consolidation_step_proofs'").fetchone():
            from .operation_consolidation import invalidate_operation_stages
            invalidate_operation_stages(self,sid,redact=redact)
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_flow_proofs'").fetchone():
            from .memory_flow import invalidate_flow
            invalidate_flow(self,sid,redact=redact)
    def set_excluded(self,sid,excluded=True):
        row=self.db.execute('SELECT * FROM controls WHERE source_id=?',(sid,)).fetchone()
        if not row or row['deleted']:raise ValueError('source unavailable')
        with self.db:
            self.db.execute('UPDATE controls SET excluded=? WHERE source_id=?',(int(excluded),sid));self.db.execute('DELETE FROM derived WHERE source_id=?',(sid,))
            self._invalidate_operation_stages(sid)
            self.bump()
    def revise(self,sid,text):
        row=self.db.execute('SELECT payload FROM inbox WHERE id=?',(sid,)).fetchone()
        if not row or not self.visible_source(sid):raise ValueError('source unavailable')
        old=json.loads(row['payload']);seq=self.next_seq();new={**old,'id':sid+'@'+str(seq),'seq':seq,'text':text}
        # Withdraw before extraction: failed rebuilding cannot serve old content.
        self.enqueue(new)
        with self.db:
            self.db.execute('UPDATE controls SET withdrawn_at=? WHERE source_id=?',(seq,sid));self.db.execute('DELETE FROM derived WHERE source_id=?',(sid,))
            self._invalidate_operation_stages(sid)
            self.bump()
        return new['id']
    def delete(self,sid):
        if not self.db.execute('SELECT 1 FROM controls WHERE source_id=?',(sid,)).fetchone():raise ValueError('unknown source')
        with self.db:
            self._invalidate_operation_stages(sid,redact=True)
            def refers(value):
                if isinstance(value,dict):return value.get('source_id')==sid or any(refers(v) for v in value.values())
                return isinstance(value,list) and any(refers(v) for v in value)
            removed_ids={r['id'] for r in self.db.execute('SELECT id FROM memory_claims WHERE source_id=?',(sid,))}
            # Purge duplicated quotations in dependent multi-source proposals.
            for row in self.db.execute('SELECT id,proposal FROM sources WHERE proposal IS NOT NULL').fetchall():
                proposal=json.loads(row['proposal']);points=proposal.get('linked_points',[])
                specs=proposal.get('linked_specs',[]);kept=[];kept_specs=[]
                for index,point in enumerate(points):
                    ordinal=specs[index].get('ordinal',index) if index<len(specs) else index
                    if any(e['source_id']==sid for e in point['evidence']):
                        meta=self.db.execute("SELECT id FROM memory_claims WHERE source_id=? AND ordinal=? AND record_kind='linked'",(row['id'],ordinal)).fetchone()
                        if meta:removed_ids.add(meta['id'])
                        self.db.execute("DELETE FROM memory_claims WHERE source_id=? AND ordinal=? AND record_kind='linked'",(row['id'],ordinal))
                    else:
                        kept.append(point)
                        if index<len(specs):kept_specs.append(specs[index])
                        else:
                            meta=self.db.execute("SELECT * FROM memory_claims WHERE source_id=? AND ordinal=? AND record_kind='linked'",(row['id'],ordinal)).fetchone()
                            kept_specs.append(dict(attribute=meta['attribute'] if meta else 'legacy:unknown',lifetime=meta['lifetime'] if meta else 'project',replace_ids=[],ordinal=ordinal))
                review=proposal.get('admission_review',{});rejected=review.get('rejected_records',[])
                safe=[r for r in rejected if not any(e['source_id']==sid for e in r.get('record',{}).get('evidence',[]))]
                proposal['linked_points']=kept
                if points or 'linked_specs' in proposal:proposal['linked_specs']=kept_specs
                if 'rejected_records' in review:review['rejected_records']=safe
                for key in ['session_points','deferred_points','diagnostics']:
                    if key in proposal:proposal[key]=[p for p in proposal[key] if not refers(p)]
                errors=proposal.get('diagnostics',[])
                self.db.execute('UPDATE sources SET proposal=?,error=? WHERE id=?',(json.dumps(proposal,ensure_ascii=False),json.dumps(errors,ensure_ascii=False) if errors else None,row['id']))
                self.db.execute('DELETE FROM model_cache WHERE source_id=?',(row['id'],))
            # Remove dangling lifecycle references without reviving old claims.
            for row in self.db.execute('SELECT id,proposal FROM sources WHERE proposal IS NOT NULL').fetchall():
                proposal=json.loads(row['proposal'])
                for key in ['claim_specs','linked_specs']:
                    for spec in proposal.get(key,[]):spec['replace_ids']=[i for i in spec.get('replace_ids',[]) if i not in removed_ids]
                if 'retract_claims' in proposal:proposal['retract_claims']=[r for r in proposal['retract_claims'] if r.get('id') not in removed_ids]
                self.db.execute('UPDATE sources SET proposal=? WHERE id=?',(json.dumps(proposal,ensure_ascii=False),row['id']))
            for claim_id in removed_ids:
                self.db.execute('DELETE FROM pending_claim_changes WHERE target_id=?',(claim_id,))
                self.db.execute('DELETE FROM pending_reminder_changes WHERE target_id=?',(claim_id,))
                self.db.execute('UPDATE memory_claims SET superseded_by=NULL WHERE superseded_by=?',(claim_id,))
                self.db.execute('UPDATE facts SET superseded_by=NULL WHERE superseded_by=?',(claim_id,))
            self._delete_operation_records(sid,removed_ids)
            self.db.execute('DELETE FROM pending_claim_changes WHERE source_id=?',(sid,))
            self.db.execute('DELETE FROM pending_reminder_changes WHERE source_id=?',(sid,))
            self.db.execute('DELETE FROM memory_claims WHERE source_id=?',(sid,))
            # Model responses can contain prior quotations even when admission
            # rejected the linked point; do not retain them after deletion.
            self.db.execute('DELETE FROM model_cache')
            self.db.execute('UPDATE controls SET deleted=1 WHERE source_id=?',(sid,))
            for table,column in [('facts','source_id'),('views','source_id'),('derived','source_id'),('pending_updates','source_id'),('model_cache','source_id'),('source_reviews','source_id')]:self.db.execute(f'DELETE FROM {table} WHERE {column}=?',(sid,))
            self.db.execute("UPDATE sources SET text='',proposal=NULL,error=NULL WHERE id=?",(sid,))
            self.db.execute("UPDATE inbox SET payload=?,state='deleted',error=NULL WHERE id=?",(json.dumps(dict(id=sid,text='[deleted]')),sid))
            self.db.execute('UPDATE audit SET detail=? WHERE source_id=?',('{}',sid))
            for audit in self.db.execute('SELECT rowid,detail FROM audit').fetchall():
                if refers(json.loads(audit['detail'])):
                    self.db.execute('UPDATE audit SET detail=? WHERE rowid=?',('{}',audit['rowid']))
            for audit in self.db.execute('SELECT rowid,detail FROM audit WHERE event IN (?,?,?)',('replace','retract_hypothesis','assert')).fetchall():
                ids=json.loads(audit['detail'])
                self.db.execute('UPDATE audit SET detail=? WHERE rowid=?',(json.dumps([i for i in ids if i not in removed_ids]),audit['rowid']))
            self.db.execute('UPDATE memory_claims SET superseded_by=NULL WHERE superseded_by=?',('retract:'+sid,))
            self.db.execute('UPDATE facts SET superseded_by=NULL WHERE superseded_by=?',('retract:'+sid,))
            self.db.execute('DELETE FROM events WHERE NOT EXISTS(SELECT 1 FROM facts f WHERE f.project=events.project AND f.entity=events.entity AND f.kind=events.kind AND f.topic=events.event_key)')
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='raw_chunks'").fetchone():
                self.db.execute('DELETE FROM raw_fts WHERE id IN (SELECT id FROM raw_chunks WHERE source_id=?)',(sid,))
                self.db.execute('DELETE FROM raw_chunks WHERE source_id=?',(sid,));self.db.execute('DELETE FROM raw_refs WHERE source_id=?',(sid,))
                self.db.execute('DELETE FROM recall_cache')
                self.db.execute('DELETE FROM embeddings WHERE text_sha NOT IN (SELECT text_sha FROM derived UNION SELECT text_sha FROM raw_refs)')
            else:self.db.execute('DELETE FROM embeddings WHERE text_sha NOT IN (SELECT text_sha FROM derived)')
            self.bump()
    def sync_views(self,units,cap=4,semantic=True):
        log=[]
        with self.db:
            for unit in units:
                fp=fingerprint(unit);views=propose(unit,cap,semantic)
                self.db.execute('DELETE FROM derived WHERE unit_id=?',(unit['id'],))
                for i,v in enumerate(views):self.db.execute('INSERT INTO derived VALUES(?,?,?,?,?,?,?,?)',(unit['id'],i,unit['source_id'],fp,digest(v['text']),v['text'],v['purpose'],json.dumps(v['fact_ids'])))
                log.append(dict(unit_id=unit['id'],count=len(views),reasons=[v['reason'] for v in views]))
        return log
    def sources(self):return [dict(r) for r in self.db.execute('SELECT id,seq,project,entity,role,sha,state FROM sources ORDER BY seq')]
    def close(self):self.db.close()
