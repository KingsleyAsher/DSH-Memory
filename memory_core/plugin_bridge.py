"""Private stdio bridge for the DSH beta. No inference or network fallback."""
import argparse
import json
import sys
from .runtime import MemoryCore
from .policy import Config
from .contract import sha
from .plugin_scopes import PluginScopes


class NoInference:
    def call(self,*args,**kwargs):raise RuntimeError('plugin never starts an independent inference call')


class PluginBridge:
    def __init__(self,home):
        config=Config(semantic=False,knowledge_enabled=False,query_planner='rules',extraction_mode='before_compact',
                      consolidation_wire='operations',consolidation_context_tokens=131072,
                      consolidation_input_tokens=65536,consolidation_output_tokens=8192,consolidation_max_sources=24)
        self.core=MemoryCore(home,config=config,model=NoInference());self.flow=self.core.memory_flow;self.db=self.core.store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS plugin_sources(id TEXT PRIMARY KEY,session_id TEXT,message_id TEXT,role TEXT);
        CREATE TABLE IF NOT EXISTS plugin_sessions(id TEXT PRIMARY KEY,state TEXT NOT NULL);
        ''')
        with self.db:self.db.execute("UPDATE plugin_sessions SET state='closed_pending' WHERE state='open'")
        self.scopes=PluginScopes(self)
        self._track_memory_changes()
        self.startup_recovery=self.recover()

    def _track_memory_changes(self):
        # Keep notification state connection-local. Existing databases need no migration.
        self.db.executescript('''
          CREATE TEMP TABLE memory_change_revision(value INTEGER NOT NULL);
          INSERT INTO memory_change_revision VALUES(0);
        ''')
        for table in ('plugin_memory_entries','plugin_memory_candidates','plugin_chat_style','plugin_windows'):
            columns=[row[1] for row in self.db.execute(f'PRAGMA table_info({table})')]
            differs=' OR '.join(f'OLD."{name}" IS NOT NEW."{name}"' for name in columns)
            for event, condition in [('INSERT',''),('UPDATE',f'WHEN {differs}'),('DELETE','')]:
                self.db.execute(f'''
                  CREATE TEMP TRIGGER notify_{table}_{event.lower()} AFTER {event} ON main.{table}
                  {condition}
                  BEGIN UPDATE memory_change_revision SET value=value+1; END
                ''')
        self.db.execute('''
          CREATE TEMP TRIGGER notify_project_retirement AFTER UPDATE ON main.plugin_session_scopes
          WHEN OLD.retired IS NOT NEW.retired OR (OLD.retired=1 AND OLD.scope_key IS NOT NEW.scope_key)
          BEGIN UPDATE memory_change_revision SET value=value+1; END
        ''')

    def memory_revision(self):
        return self.db.execute('SELECT value FROM memory_change_revision').fetchone()[0]

    def source_id(self,session,message):return 'dsh-'+sha(session+'\0'+message)[:32]

    def ingest(self,session,project,messages):
        saved=[]
        try:project=self.scopes.project_for(session,project)
        except ValueError:return dict(saved=[],state='retired_project')
        for message in messages:
            if message['role'] not in ['user','assistant','tool']:raise ValueError('unsupported_host_role')
            if not message.get('id') or not isinstance(message.get('text'),str):raise ValueError('host_source_shape')
            if not message['text'].strip():continue
            if self.db.execute('SELECT 1 FROM plugin_erased_messages WHERE session_id=? AND message_id=?',(session,message['id'])).fetchone():continue
            sid=self.source_id(session+'\0'+project,message['id'])
            self.flow.ingest(dict(id=sid,session_id=session,project=project,entity='workspace',
                                  role=message['role'],text=message['text']))
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO plugin_sources VALUES(?,?,?,?)',(sid,session,message['id'],message['role']))
            saved.append(sid)
            if message['role']=='user':self.scopes.capture_explicit(session,project,message['text'],sid)
        with self.db:self.db.execute("INSERT INTO plugin_sessions VALUES(?,'open') ON CONFLICT(id) DO UPDATE SET state='open'",(session,))
        return dict(saved=saved)

    def prepare(self,session,mode,message_ids=None):
        rows=[dict(r) for r in self.db.execute('SELECT p.*,i.seq FROM plugin_sources p JOIN inbox i ON p.id=i.id WHERE p.session_id=? ORDER BY i.seq',(session,))]
        if message_ids is not None and mode=='compaction':
            allowed=set(message_ids);rows=[r for r in rows if r['message_id'] in allowed]
        # During normal chat only prepare the latest source, plus recent context.
        # A compaction reviews all selected user/tool sources, in <=24-source
        # contracts, while still making only ONE host compaction model request.
        authored=[r for r in rows if r['role']!='assistant']
        if mode=='active':
            pending={r[0] for r in self.db.execute("SELECT source_id FROM tool_memory_reviews WHERE state='pending'")}
            authored=[r for r in authored if r['id'] in pending][:24]
        if len(authored)>192:raise ValueError('beta_compaction_source_limit_192_raw_retained')
        batches=[]
        for start in range(0,len(authored),24):
            chunk=authored[start:start+24];ids=[r['id'] for r in chunk];positions={r['id']:i for i,r in enumerate(rows)}
            lo=max(0,positions[ids[0]]-2);hi=positions[ids[-1]]+1
            context=rows[lo:hi]
            prepared=self.flow.prepare(mode,session,source_ids=ids,context_ids=[r['id'] for r in context],
                                       history_refs={r['id']:r['message_id'] if message_ids is not None and r['message_id'] in set(message_ids) else None for r in context})
            prepared['request']['system']+='\n每条f/p明确标l=global或project：跨项目稳定偏好、身份、通用约束才用global；当前项目的任务、路径、配置、进度、故障默认project。不明确用project。所有Agent共享DSH记忆；切换预设或项目不删除。project仅随对应项目激活，global跨项目适用。'
            prepared['session']=session
            batches.append(prepared)
        return dict(batches=batches)

    def prepare_active(self,session,project,message_ids):
        project=self.scopes.project_for(session,project)
        batches=self.prepare(session,'active',message_ids)['batches']
        # Resume one bounded same-workspace abandoned session in the next normal
        # main-model call. No autonomous inference and no hidden paid fallback.
        old=self.db.execute('''SELECT DISTINCT p.session_id FROM plugin_sources p
          JOIN inbox i ON p.id=i.id JOIN tool_memory_reviews r ON r.source_id=p.id
          JOIN plugin_sessions s ON s.id=p.session_id
          WHERE p.session_id!=? AND json_extract(i.payload,'$.project')=?
          AND r.state='pending' AND s.state='closed_pending' LIMIT 1''',(session,project)).fetchone()
        if old:batches+=self.prepare(old[0],'active',[])['batches']
        return dict(batches=batches)

    def submit(self,session,batch_id,memory):
        row=self.db.execute('SELECT session_id FROM memory_flow_batches WHERE id=?',(batch_id,)).fetchone()
        if not row or row['session_id']!=session:raise ValueError('batch_not_owned_by_session')
        result=self.flow.submit_tool(dict(batch_id=batch_id,memory=memory));self.scopes.sync_entries();return result

    def commit(self,session,batch_id,response):
        row=self.db.execute('SELECT session_id FROM memory_flow_batches WHERE id=?',(batch_id,)).fetchone()
        if not row or row['session_id']!=session:raise ValueError('batch_not_owned_by_session')
        result=self.flow.commit(batch_id,response);self.scopes.sync_entries();return result

    def recover(self):
        results=[]
        for row in self.db.execute("SELECT id,response FROM memory_flow_batches WHERE state='prepared' AND response IS NOT NULL").fetchall():
            try:results.append(dict(batch_id=row['id'],result=self.flow.commit(row['id'],json.loads(row['response']))))
            except (ValueError,KeyError,TypeError) as exc:results.append(dict(batch_id=row['id'],error=str(exc)))
        self.scopes.sync_entries()
        pending=self.db.execute("SELECT COUNT(*) FROM tool_memory_reviews r JOIN inbox i ON i.id=r.source_id WHERE r.state='pending' AND i.state!='deleted'").fetchone()[0]
        return dict(replayed=results,pending_sources=pending,inference_calls=0)

    def dispatch(self,request):
        op=request['op'];args=request.get('args',{})
        if op=='ingest':return self.ingest(**args)
        if op=='prepare':return self.prepare(**args)
        if op=='prepare_active':return self.prepare_active(**args)
        if op=='submit':return self.submit(**args)
        if op=='commit':return self.commit(**args)
        if op=='recover':return self.recover()
        if op=='query':
            project=self.scopes.project_for(args.get('session',''),args['project'])
            result=self.core.query(args['question'],project=project,entity='workspace',answer=False)
            archive=self.scopes.evidence(project,args['question'],legacy_sessions=args.get('legacy_sessions',[]))
            managed={r[0] for r in self.db.execute("SELECT claim_id FROM plugin_memory_entries")}
            candidates=archive+[dict(source_id=f['source_id'],value=f['value_text'],quote=f['quote'],scope='project',origin='automatic') for f in result.get('delivered',[]) if f['id'] not in managed]
            evidence=[]
            for candidate in candidates:
                if len(evidence)>=self.core.config.max_units:break
                if self.core.tokens.count(evidence+[candidate])<=self.core.config.memory_tokens:evidence.append(candidate)
            return dict(evidence=evidence,packet_tokens=self.core.tokens.count(evidence),timing=result.get('timing',{}))
        if op=='scope_activate':return self.scopes.activate(**args)
        if op=='style_project_put':return self.scopes.put_chat_style(**args)
        if op=='style_project_get':return self.scopes.get_chat_style(**args)
        if op=='scope_bind_conversation':return self.scopes.bind_conversation(**args)
        if op=='knowledge_merge':
            result=args['result'];evidence=list(result.get('evidence',[]))
            for candidate in args.get('candidates',[]):
                if len(evidence)>=self.core.config.max_units:break
                if self.core.tokens.count(evidence+[candidate])<=self.core.config.memory_tokens:evidence.append(candidate)
            return dict(result,evidence=evidence,packet_tokens=self.core.tokens.count(evidence))
        if op=='manual_add':return self.scopes.add(**args)
        if op=='review_suggest':return self.scopes.suggest(**args)
        if op=='review_list':return self.scopes.candidates(**args)
        if op=='review_resolve':return self.scopes.resolve_candidate(**args)
        if op=='manual_list':return self.scopes.list(**args)
        if op=='manual_remove':return self.scopes.remove(**args)
        if op=='scope_current':return self.scopes.window(**args)
        if op=='end':
            with self.db:self.db.execute("UPDATE plugin_sessions SET state='closed_pending' WHERE id=?",(args['session'],))
            return dict(state='durable_pending',inference_calls=0)
        if op=='status':return dict(core=self.core.status(),recovery=self.recover())
        raise ValueError('unknown_plugin_operation')

    def close(self):self.core.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--home',required=True);args=parser.parse_args()
    bridge=PluginBridge(args.home)
    try:
        for line in sys.stdin.buffer:
            request={}
            try:
                request=json.loads(line);result=dict(id=request['id'],result=bridge.dispatch(request))
            except Exception as exc:result=dict(id=request.get('id'),error=dict(type=type(exc).__name__,message=str(exc)[:500]))
            result['memory_revision']=bridge.memory_revision()
            sys.stdout.buffer.write((json.dumps(result,ensure_ascii=False)+'\n').encode('utf-8'));sys.stdout.buffer.flush()
    finally:bridge.close()


if __name__=='__main__':main()
