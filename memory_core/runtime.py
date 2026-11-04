"""One host-independent API for automatic ingest, search, answer and lifecycle."""
import json,os,re,time
from pathlib import Path
from .policy import Config,FIELD_LABELS,SCOPED_FIELDS
from .store import Store
from .providers import LocalModel,BGE
from .index import Index
from .extraction import extract,EXTRA
from .contract import PROMPT as EXTRACT_PROMPT,SCHEMA as EXTRACT_SCHEMA
from .selection import intent,retrieve
from .answering import generate,requests_for
from .views import canonical_event
from .knowledge import checked_search
from .planning import make_plan
from .atoms import frame_compatible
from .identity import resolve_scope,query_text
from .coverage import pack,covered_requests
from .raw import RawIndex
from .source_semantics import interpret

class TokenBudget:
    def __init__(self):
        self.encoder=None;self.name='utf8_bytes_upper_bound'
        cache=Path(os.environ.get('TIKTOKEN_CACHE_DIR', ''))
        if os.environ.get('TIKTOKEN_CACHE_DIR') and (cache/'fb374d419588a4632f3f557e76b4b70aebbca790').is_file():
            os.environ['TIKTOKEN_CACHE_DIR']=str(cache)
            try:
                import tiktoken
                self.encoder=tiktoken.get_encoding('o200k_base');self.name='o200k_base'
            except Exception:pass
    def count(self,value):
        text=json.dumps(value,ensure_ascii=False)
        return self.count_text(text)
    def count_text(self,text):
        return len(self.encoder.encode(text,disallowed_special=())) if self.encoder else len(text.encode('utf-8'))

class VectorAccess:
    def __init__(self,index,query,vector,enabled):self.index=index;self.query=query;self.vector=vector;self.enabled=enabled
    def get(self,text):return self.vector if text==self.query else self.index.get(text) if self.enabled else None

class MemoryCore:
    def __init__(self,home,config=None,model=None,embedding=None,knowledge=None,ranker=None,extractor=None):
        self.home=Path(home).resolve();self.home.mkdir(parents=True,exist_ok=True)
        config_path=self.home/'config.json'
        if config is None and config_path.exists():config=Config(**json.loads(config_path.read_text(encoding='utf-8')))
        self.config=config or Config();config_path.write_text(json.dumps(self.config.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
        self.store=Store(self.home/'memory.sqlite');self.model=model or LocalModel(self.store)
        # Explicitly configurable independent extractor; never fall back to a
        # host conversation API. Existing injected model clients stay compatible.
        self.extractor=extractor if extractor is not None else self.model
        self.embedding=embedding if embedding is not None else BGE() if self.config.semantic else None
        self.index=Index(self.store,self.config,self.embedding);self.tokens=TokenBudget();self.knowledge=knowledge
        self.raw=RawIndex(self.store,self.index,self.config,self.tokens)
        from .atomic_consolidation import Consolidation
        self.consolidation=Consolidation(self)
        from .thresholds import ThresholdScheduler
        self.thresholds=ThresholdScheduler(self)
        self.ranker=ranker
    @property
    def memory_flow(self):
        if not hasattr(self,'_memory_flow'):
            from .memory_flow import MemoryFlow
            self._memory_flow=MemoryFlow(self)
        return self._memory_flow
    def ingest(self,source,process=None):
        automatic=process is None and self.config.extraction_mode=='token_threshold'
        if process is None:process=self.config.extraction_mode=='immediate'
        if type(process) is not bool:raise ValueError('invalid process flag')
        receipt=self.store.enqueue(source)
        self.raw.add(json.loads(receipt['payload']))
        run=self.run_pending() if process else None
        session_id=json.loads(receipt['payload']).get('session_id','default')
        if automatic:run=self.run_threshold(session_id)
        return dict(id=source['id'],queued=receipt['state'],processing=run,
                    threshold=run['threshold'] if automatic else self.threshold_status(session_id))
    def threshold_status(self,session_id='default'):
        return self.thresholds.status(session_id)
    def run_threshold(self,session_id='default',*,retry_failed=True):
        return self.thresholds.run(session_id,retry_failed=retry_failed)
    def before_compact(self,session_id='default',*,retry_failed=True):
        return self._finalize_session(session_id,'before_compact',retry_failed)
    def before_reset(self,session_id='default',*,retry_failed=True):
        return self._finalize_session(session_id,'before_reset',retry_failed)
    def session_end(self,session_id='default',*,retry_failed=True):
        return self._finalize_session(session_id,'session_end',retry_failed)
    def _finalize_session(self,session_id,reason,retry_failed):
        out=self.consolidation.flush(session_id,reason=reason,retry_failed=retry_failed)
        if out['batches']:out['index']=self.index.ensure(self.store.units(10**12));out['raw_index']=self.raw.ensure()
        self.thresholds.settle(session_id)
        return out
    def prepare_compaction(self,session_id='default',*,retry_failed=True):
        return self.consolidation.prepare(session_id,retry_failed=retry_failed)
    def commit_compaction(self,batch_id,value,*,usage=None):
        out=self.consolidation.commit(batch_id,value,usage=usage)
        if out['state']=='committed':out['index']=self.index.ensure(self.store.units(10**12));out['raw_index']=self.raw.ensure()
        row=self.store.db.execute('SELECT session_id FROM consolidation_batches WHERE id=?',(batch_id,)).fetchone()
        if row:self.thresholds.settle(row['session_id'])
        return out
    def abort_compaction(self,batch_id,reason='host_compaction_failed'):
        self.consolidation.abort(batch_id,reason)
    def run_pending(self,limit=100,retry_failed=False):
        if retry_failed:self.store.retry_failed(self.config.max_extract_attempts)
        done=[];failed=[]
        for _ in range(limit):
            source=self.store.claim_job()
            if source is None:break
            if not self.store.visible_source(source['id']):
                with self.store.db:self.store.db.execute("UPDATE inbox SET state='cancelled' WHERE id=?",(source['id'],))
                continue
            try:
                if self.store.db.execute('SELECT 1 FROM sources WHERE id=?',(source['id'],)).fetchone():
                    with self.store.db:self.store.db.execute("UPDATE inbox SET state='done' WHERE id=?",(source['id'],))
                    continue
                from .contextual import needs_context
                recent=self.store.recent_dialogue(source)
                if source['role']=='assistant' or (re.fullmatch(r'[嗯好的是收到明白了解谢谢可以行，。！!\s]{1,16}',source['text']) and not needs_context(source,recent)):
                    result=dict(facts=[],diagnostics=[],pending_fields=[],calls=[])
                else:
                    prior=self.store.prior(source['project'],source['entity'])[-12:]
                    while prior and self.tokens.count(dict(system=EXTRACT_PROMPT+EXTRA,schema=EXTRACT_SCHEMA,payload=dict(current=source,prior=prior)))>2400:prior.pop(0)
                    if self.tokens.count(dict(system=EXTRACT_PROMPT+EXTRA,schema=EXTRACT_SCHEMA,payload=dict(current=source,prior=[])))>2800:raise ValueError('source exceeds safe local context; original and failed job retained')
                    def call(system,payload,schema,*,max_tokens):return self.extractor.call(system,payload,schema,max_tokens=max_tokens,source_id=source['id'],cache=True)
                    result=extract(source,prior,call,recent=recent,review_candidates=self.config.candidate_review)
                    if self.config.semantic_state:result=interpret(source,prior,result,call)
                state=self.store.finish(source,result);done.append(dict(id=source['id'],state=state,facts=len(result['facts']),diagnostics=result.get('diagnostics',[])))
            except Exception as exc:self.store.fail(source,type(exc).__name__+': '+str(exc));failed.append(dict(id=source['id'],error=type(exc).__name__))
        at=self.store.db.execute('SELECT COALESCE(MAX(seq),0) FROM sources').fetchone()[0]
        indexed=self.index.ensure(self.store.units(at))
        raw_index=self.raw.ensure()
        return dict(done=done,failed=failed,index=indexed,raw_index=raw_index)
    def registry(self):
        rows=self.store.sources()
        rows += [json.loads(r['payload']) for r in self.store.db.execute("SELECT payload FROM inbox WHERE state!='deleted'")]
        names={(r['project'],r['entity']) for r in rows};scopes=[dict(r) for r in self.store.db.execute('SELECT * FROM scope_keys') if (r['project'],r['entity']) in names]
        return dict(projects=sorted({r['project'] for r in rows}),entities=sorted({r['entity'] for r in rows}),scopes=scopes)
    def _barriers(self,result,project,entity,at):
        facts=[]
        for field,reason in result.get('blocked_fields',{}).items():
            pending=self.store.db.execute('SELECT p.source_id id,p.seq,i.payload FROM pending_updates p JOIN inbox i ON i.id=p.source_id JOIN controls c ON c.source_id=i.id WHERE p.project=? AND p.entity=? AND p.field=? AND p.seq<=? AND (p.resolved_at IS NULL OR p.resolved_at>?) AND c.excluded=0 AND c.deleted=0 AND (c.withdrawn_at IS NULL OR c.withdrawn_at>?) ORDER BY p.seq DESC LIMIT 1',(project,entity,field,at,at,at)).fetchone()
            if pending:
                text=json.loads(pending['payload'])['text'];quote=next((p for p in re.split('[。；;]',text) if re.search({'reminder_time':'通知|提醒|钟点','archive_path':'目录|路径|归档','service_port':'端口|监听','contact_phone':'电话|手机'}.get(field,field),p)),text)
                facts.append(dict(id='barrier:'+pending['id']+':'+field,source_id=pending['id'],seq=pending['seq'],project=project,entity=entity,field=field,topic='',kind='fact',epistemic='unknown',value='',value_text=quote,quote=quote,valid_to=None,control=True))
            else:
                values=[f for f in self.store.facts(at) if f['project']==project and f['entity']==entity and f['field']==field and f['kind']=='fact']
                for f in values[:3]:facts.append({**f,'control':True,'epistemic':'unknown'})
        return facts
    def query(self,question,*,project=None,entity=None,project_id=None,entity_id=None,event=None,at=None,answer=True,answer_mode='atomic',fresh_query_vector=False):
        if not isinstance(question,str) or not question.strip() or len(question)>4000:raise ValueError('invalid query')
        started=time.perf_counter();registry=self.registry();p,e,scope_method=resolve_scope(question,registry,dict(project=project,entity=entity,project_id=project_id,entity_id=entity_id))
        if not p or not e:return dict(value=dict(answerable=False,answer='对象范围不明确，无法可靠查询。',source_ids=[]),assertions=[],guarded=True,packet=[],delivered=[],timing=dict(total_ms=(time.perf_counter()-started)*1000),retrieval=dict(abstain=True,reason='scope_ambiguous'))
        task_question,normalized=query_text(question,p,e,event)
        at=at if at is not None else self.store.db.execute('SELECT COALESCE(MAX(seq),0) FROM inbox').fetchone()[0]
        d=intent(normalized);units=[u for u in self.store.units(at,d['historical'],p,e) if (u['kind']=='example')==d['example']]
        event_names={u['event_key'] for u in units if u.get('event_key')}
        all_frames=[f for u in units for f in u['facts']]
        ledger_aliases=[]
        if hasattr(self.store,'claim_aliases'):
            from .query_events import attach_aliases
            ledger_aliases=self.store.claim_aliases(at,p,e)
            attach_aliases(all_frames,ledger_aliases)
        plan,planning=make_plan(task_question,all_frames,self.model,self.config.query_planner)
        event_request=any(r['field'] in SCOPED_FIELDS|{'any'} and not r.get('event') for r in plan)
        if event_request and not event and re.search(r'那次|那个问题|那件',question) and not any(n in question for n in event_names) and len(event_names)>1:
            return dict(value=dict(answerable=False,answer='未能确定具体事件，无法可靠回答。',source_ids=[]),assertions=[],guarded=True,packet=[],delivered=[],packet_tokens=0,timing=dict(total_ms=(time.perf_counter()-started)*1000),retrieval=dict(abstain=True,reason='event_ambiguous'))
        t=time.perf_counter();indexed=self.index.ensure(units);index_ms=(time.perf_counter()-t)*1000
        t=time.perf_counter();qvec=self.index.query_vector(normalized,fresh=fresh_query_vector);embedding_ms=(time.perf_counter()-t)*1000
        vectors=VectorAccess(self.index,normalized,qvec,self.config.semantic);logs=[];ids=set();result=None
        t=time.perf_counter()
        for round_no in range(1,self.config.max_rounds+1):
            new,log=self.index.candidates(normalized,units,qvec,round_no,requests=plan)
            for uid in sorted(new):
                if len(ids)<self.config.candidate_limit:ids.add(uid)
            logs.append(log)
            result=retrieve(self.store,normalized,at,registry,vectors,cap=self.config.view_cap,allowed_unit_ids=ids,max_units=self.config.max_units,request_plan=plan,scope=(p,e),weights=self.config.ranking_weights,ranker=self.ranker)
            if result['answer_facts'] and all(r['field'] in result.get('blocked_fields',{}) or any(frame_compatible(f,r) for f in result['answer_facts']) for r in plan):break
        retrieval_ms=(time.perf_counter()-t)*1000
        t=time.perf_counter();facts=self._barriers(result,p,e,at)+result['answer_facts']
        if self.config.knowledge_enabled:
            for r in checked_search(self.knowledge,question,p,e):
                if (r['kind']=='example')!=d['example']:continue
                if any(f['field']==r['field'] for f in facts) and not re.search(r'知识库|文档|手册',question):continue
                external={**r,'id':'knowledge:'+r['source_id']+':'+r['version'],'source_id':'kb:'+r['source_id']+'@'+r['version'],'origin_source_id':r['source_id'],'seq':at,'topic':r.get('event_key',''),'value':r.get('value',r['value_text']),'valid_to':None}
                facts.append(external)
        if ledger_aliases:
            from .query_events import attach_aliases
            attach_aliases(facts,ledger_aliases)
        # Apply the same request/frame contract before spending context budget.
        facts=[f for f in facts if any(frame_compatible(f,r) for r in plan)]
        def make_item(f,index):
            item={k:f[k] for k in ['id','source_id','project','entity','field','topic','kind','epistemic','value','value_text','quote']}
            item.update(evidence_id='E'+str(index),temporal_scope='历史记录' if d['historical'] else '教学示例' if d['example'] else '当前实际记录')
            if f.get('control'):item['control']=True
            if f.get('reminder_event'):item['reminder_event']=True
            for key in ['category','property','event_id','event_aliases']:
                if key in f:item[key]=f[key]
            if f.get('record_kind') in ['linked','operation']:
                item.update(record_kind='linked',attribute=f['attribute'],evidence=f['evidence'],source_ids=f['source_ids'])
                item['record_kind']=f['record_kind']
            for key in ['operation_action','operation_target_values','operation_target_ids']:
                if key in f:item[key]=f[key]
            return item
        selected,packet,packet_coverage=pack(facts,plan,make_item,self.tokens.count,self.config.memory_tokens)
        packet_tokens=self.tokens.count(packet) if packet else 0;packet_ms=(time.perf_counter()-t)*1000
        recovery=dict(attempted=False,trigger=None,accepted=0)
        # A missing summary or a failed generated answer can cause one reread.
        # Known unresolved values aren't healed by copying older raw literals.
        missing=any(not any(frame_compatible(f,r) for f in facts) for r in plan)
        recoverable=any(r['field']!='credential' for r in plan)
        def reread(trigger):
            nonlocal facts,selected,packet,packet_coverage,packet_tokens,recovery
            extra,recovery=self.raw.recover(question,plan,p,e,at,qvec,d['historical'],d['example'],result.get('blocked_fields',{}),self.extractor,trigger)
            if not extra:return False
            # Replace a summary for the same source and frame with its fuller
            # original quote; leave unrelated evidence and controls intact.
            keys={(f['source_id'],f['field'],f['topic'],f['kind']) for f in extra}
            healed={f['field'] for f in extra if f['field'] in result.get('blocked_fields',{})}
            facts=[f for f in facts if (f['source_id'],f['field'],f['topic'],f['kind']) not in keys and not (f.get('control') and f['field'] in healed)]+extra
            selected,packet,packet_coverage=pack(facts,plan,make_item,self.tokens.count,self.config.memory_tokens)
            packet_tokens=self.tokens.count(packet) if packet else 0
            return True
        if answer and self.config.raw_recall and missing and recoverable:reread('missing_frame')
        if answer:
            if answer_mode=='atomic':response=generate(question,packet,result['reason'],self.model,self.config.answer_tokens,request_plan=plan)
            elif answer_mode=='legacy':
                from .legacy_answer import generate as old_generate
                plain=[dict(source_id=f['source_id'],project=f['project'],entity=f['entity'],field=f['field'],value=f['value'],value_text=f['value_text'],epistemic=f['epistemic'],quote=f['quote'],event_name=f['topic'],temporal_scope=f['temporal_scope']) for f in packet]
                response=old_generate(question,plain,result['reason'],self.model.call)
            else:raise ValueError('invalid answer mode')
        else:response=dict(value=None,assertions=[],wall_ms=0,attempts=0)
        known_unavailable=all(any(frame_compatible(f,r) and (f.get('control') or (r.get('mode')=='confirmed' and f['epistemic'] in ['unknown','hypothesis'])) for f in packet) for r in plan)
        if answer and answer_mode=='atomic' and self.config.raw_recall and not recovery.get('searched') and recoverable and not known_unavailable and (response.get('guarded') or (not response.get('value',{}).get('answerable') and not any(f.get('control') for f in packet))):
            previous=response
            if reread('answer_validation' if response.get('guarded') else 'answer_unavailable'):
                response=generate(question,packet,result['reason'],self.model,self.config.answer_tokens,request_plan=plan,max_attempts=1)
                response['before_recovery']=previous
                for key in ['wall_ms','attempts','prompt_eval_count','eval_count']:response[key]=response.get(key,0)+previous.get(key,0)
        packed_packet=packet;packed_selected=selected
        if answer and answer_mode=='atomic':
            sent=set(response.get('sent_evidence_ids',[]));packet=[f for f in packet if f['evidence_id'] in sent];sent_facts={f['id'] for f in packet};selected=[f for f in selected if f['id'] in sent_facts]
            packet_tokens=self.tokens.count(packet) if packet else 0
        total=(time.perf_counter()-started)*1000
        return dict(**response,raw_recovery=recovery,packet=packet,delivered=selected,packed_packet=packed_packet,packed_delivered=packed_selected,packet_tokens=packet_tokens,token_counter=self.tokens.name,index=indexed,retrieval=result,paths=logs,request_plan=plan,planning=planning,packet_coverage=packet_coverage,scope=dict(project=p,entity=e,method=scope_method),retrieval_query=normalized,
            timing=dict(planning_ms=planning['wall_ms'],index_ms=index_ms,query_embedding_ms=embedding_ms,retrieval_ms=retrieval_ms,packet_ms=packet_ms,mimo_ms=response.get('wall_ms',0),total_ms=total),generation=self.store.generation(),semantic_error=self.index.error)
    def exclude(self,sid,excluded=True):self.store.set_excluded(sid,excluded);self.consolidation.invalidate();self.index.cache.clear()
    def delete(self,sid):
        self.store.delete(sid);self.consolidation.invalidate();self.index.cache.clear()
        with self.store.db:self.store.db.execute('DELETE FROM source_token_counts WHERE source_id=?',(sid,))
    def revise(self,sid,text,process=None):
        automatic=process is None and self.config.extraction_mode=='token_threshold'
        if process is None:process=self.config.extraction_mode=='immediate'
        if type(process) is not bool:raise ValueError('invalid process flag')
        new=self.store.revise(sid,text);self.index.cache.clear()
        self.consolidation.invalidate()
        session_id=self.store.db.execute('SELECT session_id FROM inbox WHERE id=?',(new,)).fetchone()[0]
        run=self.run_pending() if process else self.run_threshold(session_id) if automatic else None
        return dict(id=new,processing=run,threshold=self.threshold_status(session_id))
    def status(self):
        return dict(generation=self.store.generation(),sources=len(self.store.sources()),facts=len(self.store.facts()),context_points=len(self.store.extracted_context_points()),extraction_backend=type(self.extractor).__name__,extraction_backend_separate=self.extractor is not self.model,consolidation=self.consolidation.status(),jobs=[dict(r) for r in self.store.db.execute('SELECT state,COUNT(*) n FROM inbox GROUP BY state')],semantic=self.config.semantic,vector_bytes=self.store.db.execute('SELECT COALESCE(SUM(length(data)),0) FROM embeddings').fetchone()[0],knowledge_enabled=self.config.knowledge_enabled)
    def close(self):self.store.close()
