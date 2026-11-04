"""Bounded, restartable semantic-operation consolidation (reserved wire V4)."""
import json
import re
import time
import uuid

from . import compact_wire, operation_wire
from .atomic_wire import estimate_output, target_candidates
from .consolidation import Consolidation as LegacyScheduler
from .contract import sha
from .reminders import is_event_reminder, reminder_axis


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)


def invalidate_operation_stages(store,source_id,redact=False):
    """Invalidate derived requests inside the caller's controls transaction.

    No transaction/commit here: delete must erase raw and derived copies in the
    same transaction. A response hash is retained as an erasure audit, not text.
    """
    db=store.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='consolidation_step_proofs'").fetchone():return 0
    rows=db.execute('''SELECT DISTINCT s.batch_id FROM consolidation_steps s
        JOIN consolidation_step_proofs p ON p.step_id=s.id WHERE p.source_id=?''',(source_id,)).fetchall()
    for row in rows:
        bid=row['batch_id'];batch=db.execute('SELECT * FROM consolidation_batches WHERE id=?',(bid,)).fetchone()
        if batch and batch['state']=='prepared':
            reason='operation_proof_source_controls_changed'
            db.execute("UPDATE consolidation_batches SET state='failed',summary=NULL,error=? WHERE id=?",(reason,bid))
            db.execute("UPDATE consolidation_steps SET state='failed',consumed_at=? WHERE batch_id=? AND state='prepared'",(time.time(),bid))
            for sid in json.loads(batch['source_ids']):
                db.execute("UPDATE inbox SET state='failed',lease_until=0,error=? WHERE id=? AND state='working'",(reason,sid))
        if redact:
            db.execute("UPDATE consolidation_steps SET request='{}',response=NULL,redacted=1 WHERE batch_id=?",(bid,))
            db.execute("UPDATE consolidation_operation_state SET first_value='{}',lookup_refs='{}',lookup_requests='[]',wire_failed='{}' WHERE batch_id=?",(bid,))
            db.execute('DELETE FROM consolidation_step_proofs WHERE step_id IN (SELECT id FROM consolidation_steps WHERE batch_id=?)',(bid,))
    return len(rows)


class OperationEngine:
    def __init__(self,base):
        self.base=base;self.core=base.core;self.store=base.store;self.db=base.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS consolidation_steps(
          id TEXT PRIMARY KEY,batch_id TEXT,stage TEXT,state TEXT,request TEXT,
          created_at REAL,consumed_at REAL,response TEXT,response_hash TEXT,usage TEXT,redacted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS consolidation_step_proofs(
          step_id TEXT,source_id TEXT,PRIMARY KEY(step_id,source_id));
        CREATE TABLE IF NOT EXISTS consolidation_operation_state(
          batch_id TEXT PRIMARY KEY,first_value TEXT,lookup_refs TEXT,
          lookup_requests TEXT,wire_failed TEXT);
        ''')
        columns={r['name'] for r in self.db.execute('PRAGMA table_info(consolidation_steps)')}
        for name,kind in [('response','TEXT'),('response_hash','TEXT'),('usage','TEXT'),('redacted','INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:self.db.execute('ALTER TABLE consolidation_steps ADD COLUMN '+name+' '+kind)
        self.db.commit()

    def _step(self,batch_id):
        return self.db.execute("SELECT * FROM consolidation_steps WHERE batch_id=? AND state='prepared' ORDER BY created_at,id LIMIT 1",(batch_id,)).fetchone()

    def _new_step(self,batch_id,stage,request,proof_sources=()):
        sid='step-'+uuid.uuid4().hex
        self.db.execute('''INSERT INTO consolidation_steps(id,batch_id,stage,state,request,created_at,consumed_at,response,response_hash,usage)
            VALUES(?,?,?,?,?,?,NULL,NULL,NULL,NULL)''',
            (sid,batch_id,stage,'prepared',encoded(request),time.time()))
        for source_id in set(proof_sources):self.db.execute('INSERT OR IGNORE INTO consolidation_step_proofs VALUES(?,?)',(sid,source_id))
        return sid

    @staticmethod
    def _proof_sources(rows):
        ids=set()
        for row in rows:
            if row.get('source_id'):ids.add(row['source_id'])
            ids.update(row.get('source_ids',[]))
            for e in row.get('evidence',row.get('point',{}).get('evidence',[])):
                if e.get('source_id'):ids.add(e['source_id'])
        return ids

    def _lookup_snapshot_valid(self,batch):
        state=self.db.execute('SELECT * FROM consolidation_operation_state WHERE batch_id=?',(batch['id'],)).fetchone()
        if not state:return False
        refs=json.loads(state['lookup_refs'])
        for entry in json.loads(state['lookup_requests']):
            row=self.db.execute('SELECT payload FROM inbox WHERE id=?',(entry['source_id'],)).fetchone()
            if not row:return False
            catalog={r['id']:r for r in self.store.claim_catalog(json.loads(row['payload']))}
            for card in entry['targets']:
                actual=catalog.get(refs.get(card['id']))
                if not actual or operation_wire.target_packet(actual,card['id'])!=card:return False
        return True

    def _consume_write(self,step,value,usage,*,failed=False):
        body=encoded(value);digest=sha(body)
        current=self.db.execute('SELECT * FROM consolidation_steps WHERE id=?',(step['id'],)).fetchone()
        if current['response_hash'] is not None:
            if current['response_hash']!=digest:raise ValueError('operation_first_response_changed')
            return
        self.db.execute('UPDATE consolidation_steps SET state=?,consumed_at=?,response=?,response_hash=?,usage=? WHERE id=?',
            ('failed' if failed else 'consumed',time.time(),body,digest,encoded(usage or {}),step['id']))

    def _consume(self,step,value,usage,*,failed=False):
        with self.db:self._consume_write(step,value,usage,failed=failed)

    def _prepared(self,batch,step):
        request=json.loads(step['request']);input_cap,_,context_cap=self.base._budgets()
        if self.core.tokens.count(request)>input_cap:
            return dict(state='blocked',source_id=json.loads(batch['source_ids'])[0],reason='operation_resume_input_budget')
        return dict(state='prepared',batch_id=batch['id'],session_id=batch['session_id'],
            source_ids=json.loads(batch['source_ids']),step_id=step['id'],stage=step['stage'],wire_version=4,
            estimated_input_tokens=self.core.tokens.count(request),estimated_output_tokens=request['max_tokens'],
            output_limit=request['max_tokens'],context_limit=context_cap,summary_scope='batch_delta',request=request)

    def _resume(self,session_id):
        row=self.db.execute('''SELECT b.* FROM consolidation_batches b JOIN consolidation_reservations r ON r.batch_id=b.id
            WHERE b.session_id=? AND b.state='prepared' AND r.wire_version=4 ORDER BY b.rowid LIMIT 1''',(session_id,)).fetchone()
        if not row:return None
        step=self._step(row['id'])
        if not step:
            self.abort(row['id'],'operation_missing_stage');return None
        if step['stage']=='lookup' and not self._lookup_snapshot_valid(row):
            self.abort(row['id'],'operation_lookup_targets_changed');return None
        # Reacquire this immutable, not-yet-consumed stage before the legacy
        # expiry recovery. No source attempt is added; no completed work repeats.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            ids=json.loads(row['source_ids']);valid=True
            for sid in ids:
                source=self.db.execute('SELECT state,lease_until FROM inbox WHERE id=?',(sid,)).fetchone()
                valid=valid and bool(source and source['state']=='working' and source['lease_until']==row['lease_until'] and self.store.visible_source(sid))
            if not valid:
                self.abort(row['id'],'operation_source_changed');return None
            lease=time.time()+300
            self.db.execute('UPDATE consolidation_batches SET lease_until=? WHERE id=?',(lease,row['id']))
            for sid in ids:self.db.execute('UPDATE inbox SET lease_until=? WHERE id=?',(lease,sid))
        return self._prepared(self.db.execute('SELECT * FROM consolidation_batches WHERE id=?',(row['id'],)).fetchone(),step)

    def prepare(self,session_id='default',*,retry_failed=False,_skip_source_ids=()):
        session_id=self.base.session(session_id)
        continued=self._resume(session_id)
        if continued:return continued
        if self.core.config.consolidation_wire!='operations':
            return self.base.prepare(session_id,retry_failed=retry_failed,_skip_source_ids=_skip_source_ids,_operation_bypass=True)
        self.base._recover();input_cap,output_cap,context_cap=self.base._budgets()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');rows=self.base._rows(session_id)
            if any(r['state']=='working' and self.base._visible(r) for r in rows):return dict(state='busy',session_id=session_id)
            eligible=[r for r in rows if self.base._visible(r) and r['state'] not in ['done','deleted','cancelled']]
            if not eligible:self.base._advance(session_id);return dict(state='empty',session_id=session_id)
            available=[r for r in eligible if r['id'] not in _skip_source_ids and
                (r['state']!='failed' or retry_failed and r['attempts']<self.core.config.max_extract_attempts)]
            if not available:return dict(state='blocked',source_id=eligible[0]['id'],reason='failed_delta_retained')
            first=available[0];source=json.loads(first['payload']);catalog=self.store.claim_catalog(source)
            bound=self.db.execute('SELECT max_sources FROM consolidation_limits WHERE session_id=? AND project=? AND entity=?',(session_id,source['project'],source['entity'])).fetchone()
            limit=min(self.core.config.consolidation_max_sources,bound[0] if bound else self.core.config.consolidation_max_sources)
            selected=[];final=None;final_context=[];final_refs={};final_targets=[];estimate=0;final_estimate=0
            for row in available:
                current=json.loads(row['payload'])
                if (current['project'],current['entity'])!=(source['project'],source['entity']):break
                candidate=selected+[current]
                estimate=estimate_output(candidate,self.core.tokens.count)+24*sum(s['role']!='assistant' for s in candidate)
                if estimate>output_cap:break
                contexts,required=self.base._context_plan(candidate)
                if required-({s['id'] for s in contexts}|{s['id'] for s in candidate}):break
                targets,_=target_candidates(catalog,candidate)
                def request():
                    refs={'T'+str(i):t['id'] for i,t in enumerate(targets,1)}
                    entries=[dict(t,ref=ref) for ref,t in zip(refs,targets)]
                    return operation_wire.build_request(candidate,contexts,entries,output_cap),refs
                body,refs=request()
                # The model has an explicit lookup operation, so omitted
                # directory entries cannot be silently treated as no old claim.
                while targets and self.core.tokens.count(body)>input_cap:targets.pop();body,refs=request()
                while self.core.tokens.count(body)>input_cap and self.base._drop_optional_context(contexts,required,candidate):body,refs=request()
                if self.core.tokens.count(body)>input_cap:break
                selected=candidate;final=body;final_refs=refs;final_context=list(contexts);final_targets=list(targets);final_estimate=estimate
                if len(selected)>=limit:break
            if not selected:
                self.db.execute("UPDATE inbox SET state='failed',error='operation_input_or_output_budget',attempts=attempts+1 WHERE id=?",(first['id'],))
                return dict(state='blocked',source_id=first['id'],reason='operation_input_or_output_budget')
            batch_id='operations-'+uuid.uuid4().hex;lease=time.time()+300;ids=[s['id'] for s in selected]
            self.db.execute('INSERT INTO consolidation_batches VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (batch_id,session_id,source['project'],source['entity'],json.dumps(ids),'prepared',lease,sha(encoded(final)),None,'{}',None))
            self.db.execute('''INSERT INTO consolidation_reservations
                (batch_id,refs,context_ids,output_limit,estimated_output,wire_version,wire_map) VALUES(?,?,?,?,?,?,?)''',
                (batch_id,encoded(final_refs),json.dumps([s['id'] for s in final_context]),output_cap,final_estimate,4,encoded(compact_wire.handles_for(selected,final_context))))
            proof_sources={s['id'] for s in selected+final_context}|self._proof_sources(final_targets)
            self._new_step(batch_id,'extract',final,proof_sources)
            for sid in ids:self.db.execute("UPDATE inbox SET state='working',attempts=attempts+1,lease_until=?,error=NULL WHERE id=?",(lease,sid))
        batch=self.db.execute('SELECT * FROM consolidation_batches WHERE id=?',(batch_id,)).fetchone()
        result=self._prepared(batch,self._step(batch_id));result['estimated_output_tokens']=final_estimate
        return result

    def _sources(self,batch,reservation):
        sources=[];context=[]
        for sid in json.loads(batch['source_ids']):
            row=self.db.execute('SELECT * FROM inbox WHERE id=?',(sid,)).fetchone()
            if not row or not self.store.visible_source(sid) or row['state']!='working' or row['lease_until']!=batch['lease_until'] or batch['lease_until']<time.time():raise ValueError('batch_source_changed_or_lease_expired')
            sources.append(json.loads(row['payload']))
        for sid in json.loads(reservation['context_ids']):
            row=self.db.execute('SELECT payload FROM inbox WHERE id=?',(sid,)).fetchone()
            if not row or not self.store.visible_source(sid):raise ValueError('atomic_context_changed')
            context.append(json.loads(row['payload']))
        return sources,context

    @staticmethod
    def _grams(text):
        text=re.sub(r'[\W_]+','',text.lower())
        return {text[i:i+2] for i in range(max(0,len(text)-1))}

    def _lookup_candidates(self,source,op):
        rows=self.store.claim_catalog(source);query=self._grams(op['query']+' '+op['event'])
        if op['category']=='reminder':
            rows=[r for r in rows if r.get('category')=='reminder' or is_event_reminder(r,r.get('attribute',''))]
            rows=[r for r in rows if (r.get('property') if r.get('category')=='reminder' else reminder_axis(r,r.get('attribute','')))==op['property']]
        # This is candidate recall, not a decision to mutate. All candidates
        # remain eligible for the bounded language binder; no lexical winner
        # is committed. Unselected recall candidates are not proof obligations.
        def score(row):
            words=self._grams(' '.join(str(row.get(k,'')) for k in ['topic','attribute','value']))
            return len(query&words)/max(1,len(query)),row['seq'],row['id']
        return sorted(rows,key=score,reverse=True)[:8]

    def _lookup_request(self,batch,reservation,pending):
        directory={};operations=[]
        for entry in pending:
            for card in entry['targets']:directory[card['id']]=card
            operation={k:v for k,v in entry.items() if k not in ['source_id','op_index','targets']}
            operation['targets']=[card['id'] for card in entry['targets']]
            operations.append(operation)
        return dict(system=operation_wire.LOOKUP_PROMPT,
            payload=dict(scope=[batch['project'],batch['entity']],targets=list(directory.values()),operations=operations),
            schema=operation_wire.lookup_schema([x['id'] for x in pending]),max_tokens=reservation['output_limit'])

    def _budget_lookup(self,batch,reservation,pending,failed):
        """Select whole cards fairly; never omit an operation of a live source.

        The first two ranked candidates (or the sole candidate) protect each
        operation before any operation receives more. If those minima cannot
        coexist in one bounded request, isolate whole source transactions.
        """
        input_cap,_,_=self.base._budgets()
        def fits(entries):return self.core.tokens.count(self._lookup_request(batch,reservation,entries))<=input_cap
        if fits(pending):return pending
        minimum=[dict(entry,targets=entry['targets'][:2]) for entry in pending]
        if fits(minimum):selected=minimum
        else:
            selected=[];groups={}
            for entry in minimum:groups.setdefault(entry['source_id'],[]).append(entry)
            for sid,entries in groups.items():
                if fits(selected+entries):selected+=entries
                else:failed[sid]=dict(error='ValueError',reason='operation_lookup_input_budget')
        # Round-robin by next rank, so a long candidate list cannot consume
        # the budget before another operation obtains its minimum evidence.
        originals={entry['id']:entry for entry in pending}
        for rank in range(2,8):
            for index,entry in enumerate(selected):
                cards=originals[entry['id']]['targets']
                if rank>=len(cards):continue
                trial=list(selected);trial[index]=dict(entry,targets=entry['targets']+[cards[rank]])
                if fits(trial):selected=trial
        return selected

    def _make_lookup(self,batch,reservation,sources,decoded,failed):
        pending=[];extra_refs={};claim_handles={};next_ref=max([int(k[1:]) for k in json.loads(reservation['refs'])]+[0])+1
        rows_by_ref={}
        for source in sources:
            result=decoded.get(source['id'])
            if not result:continue
            for index,op in enumerate(result['mutation_ops']):
                if source['id'] in failed or not op['query']:continue
                candidates=self._lookup_candidates(source,op)
                if not candidates:
                    failed[source['id']]=dict(error='ValueError',reason='operation_lookup_no_candidates');continue
                cards=[]
                for row in candidates:
                    if row['id'] not in claim_handles:
                        handle='T'+str(next_ref);next_ref+=1;claim_handles[row['id']]=handle;extra_refs[handle]=row['id']
                    ref=claim_handles[row['id']];rows_by_ref[ref]=row
                    cards.append(operation_wire.target_packet(row,ref))
                entry=dict(id='O'+str(len(pending)+1),source_id=source['id'],op_index=index,
                    action=op['action'],event=op['event'],category=op['category'],property=op['property'],
                    query=op['query'],quote=op['quote'],targets=cards)
                pending.append(entry)
        # A source with one unresolved operation must not consume a binder
        # slot for its other operations or block unrelated source commits.
        pending=[entry for entry in pending if entry['source_id'] not in failed]
        pending=self._budget_lookup(batch,reservation,pending,failed) if pending else []
        selected_refs={card['id'] for entry in pending for card in entry['targets']}
        extra_refs={ref:cid for ref,cid in extra_refs.items() if ref in selected_refs}
        proof_sources={entry['source_id'] for entry in pending}|self._proof_sources([rows_by_ref[ref] for ref in selected_refs])
        request=self._lookup_request(batch,reservation,pending) if pending else None
        return request,extra_refs,pending,failed,proof_sources

    def _bind(self,value,pending,decoded):
        if not isinstance(value,dict) or set(value)!={'bindings'} or not isinstance(value['bindings'],list) or len(value['bindings'])!=len(pending):raise ValueError('operation_binding_coverage')
        expected={p['id']:p for p in pending};seen=set();failed={}
        for row in value['bindings']:
            if not isinstance(row,dict) or set(row)!={'id','t'} or not isinstance(row['id'],str) or row['id'] not in expected or row['id'] in seen:raise ValueError('operation_binding_id')
            seen.add(row['id']);entry=expected[row['id']];targets=row['t'];allowed={c['id'] for c in entry['targets']}
            if not isinstance(targets,list) or len(targets)>4 or any(not isinstance(t,str) or t not in allowed for t in targets) or len(set(targets))!=len(targets):raise ValueError('operation_binding_target')
            if not targets:failed[entry['source_id']]=dict(error='ValueError',reason='operation_lookup_unresolved');continue
            op=decoded[entry['source_id']]['mutation_ops'][entry['op_index']]
            op['target_refs']=targets;op['query']=''
        return failed

    def _pending_known(self,sources,decoded,refs):
        if not hasattr(self.store,'mark_operation_pending'):return
        for source in sources:
            result=decoded.get(source['id'])
            if not result or source['role']!='user':continue
            targets={refs[r] for op in result['mutation_ops'] if op['action'] in ['replace','retract'] for r in op['target_refs'] if r in refs}
            if targets:self.store.mark_operation_pending(source,sorted(targets))

    def _finish(self,batch,reservation,sources,context,decoded,failed,summary,refs):
        done=[];errors=[]
        def resolve(ref,current):
            if ref in refs:return refs[ref]
            match=re.fullmatch(r'(.+)#([FL])(\d+)',ref)
            if not match:raise ValueError('unknown_operation_target_ref')
            sid,kind,index=match.groups()
            earlier=next((s for s in sources if s['id']==sid and s['seq']<current['seq']),None)
            state=self.db.execute('SELECT state FROM inbox WHERE id=?',(sid,)).fetchone()
            if not earlier or not state or state['state']!='done':raise ValueError('operation_dependency_source_not_done')
            claim=self.store.claim_by_ref(sid,int(index),'fact' if kind=='F' else 'linked')
            claim=claim['id'] if isinstance(claim,dict) else claim
            if not claim:raise ValueError('operation_target_not_durable')
            return claim
        for source in sources:
            sid=source['id']
            try:
                if sid in failed:raise ValueError(failed[sid]['reason'])
                result=decoded[sid]
                for spec in result['claim_specs']+result['linked_specs']:
                    if spec.pop('replace_refs',[]):raise ValueError('operation_implicit_replacement')
                    spec['replace_ids']=[]
                for op in result['mutation_ops']:
                    if op.pop('query',''):raise ValueError('operation_unresolved_query')
                    op['target_ids']=[resolve(ref,source) for ref in op.pop('target_refs')]
                self.base._check_configuration_order(source,result)
                state=self.store.finish_atomic(source,result,linked_context=context+sources,strict=True)
                done.append(dict(id=sid,state=state,facts=len(result['facts']),session_points=len(result['session_points']),diagnostics=result['diagnostics']))
            except (ValueError,TypeError,KeyError) as exc:
                error=dict(id=sid,state='failed',error=type(exc).__name__,reason=str(exc)[:300]);self.store.fail(source,error['error']+':'+error['reason']);errors.append(error)
        usage=[json.loads(r['usage'] or '{}') for r in self.db.execute('SELECT usage FROM consolidation_steps WHERE batch_id=?',(batch['id'],))]
        aggregate=dict(model_calls=sum(x.get('model_calls',0) for x in usage),stages=len(usage))
        with self.db:
            self.db.execute("UPDATE consolidation_batches SET state='committed',summary=?,usage=?,error=? WHERE id=?",
                (summary if not errors else None,encoded(aggregate),encoded(errors) if errors else None,batch['id']))
            self.base._advance(batch['session_id'])
        return dict(state='committed',batch_id=batch['id'],complete=not errors,done=done,failed=errors,
            continuation_summary=summary if not errors else '',summary_withheld=bool(errors),summary_scope='batch_delta',wire_version=4,processing_stages=len(usage))

    def commit(self,batch_id,value,*,usage=None):
        batch=self.db.execute('SELECT * FROM consolidation_batches WHERE id=?',(batch_id,)).fetchone()
        if not batch:raise ValueError('unknown batch')
        if batch['state']=='committed':
            failed=json.loads(batch['error']) if batch['error'] else []
            return dict(state='already_committed',batch_id=batch_id,complete=not failed,failed=failed,model_calls=0)
        if batch['state']!='prepared':raise ValueError('batch no longer prepared')
        step=self._step(batch_id)
        if not step:raise ValueError('operation_missing_stage')
        reservation=self.db.execute('SELECT * FROM consolidation_reservations WHERE batch_id=?',(batch_id,)).fetchone()
        state=self.db.execute('SELECT * FROM consolidation_operation_state WHERE batch_id=?',(batch_id,)).fetchone()
        # Host retry of the initial commit is idempotent while binding is pending.
        if step['stage']=='lookup' and state and encoded(value)==state['first_value']:
            return dict(state='lookup_required',batch_id=batch_id,complete=False,failed=[],continuation_summary='',summary_withheld=True,next=self._prepared(batch,step))
        try:
            if self.core.tokens.count(value)>json.loads(step['request'])['max_tokens']:raise ValueError('operation_output_budget_exceeded')
            sources,context=self._sources(batch,reservation);mapping=json.loads(reservation['wire_map'])
            first=json.loads(state['first_value']) if step['stage']=='lookup' else value
            decoded,failed,summary=operation_wire.decode(first,sources,context,mapping)
            refs=json.loads(reservation['refs'])
            if step['stage']=='extract':
                request,extra,pending,failed,lookup_proofs=self._make_lookup(batch,reservation,sources,decoded,failed)
                if request:
                    self._pending_known(sources,decoded,refs)
                    with self.db:
                        # Consume the immutable first response and reserve its
                        # continuation atomically; no consumed/no-next-stage gap.
                        self._consume_write(step,value,usage)
                        self.db.execute('INSERT INTO consolidation_operation_state VALUES(?,?,?,?,?)',
                            (batch_id,encoded(value),encoded(extra),encoded(pending),encoded(failed)))
                        inherited={r['source_id'] for r in self.db.execute('SELECT source_id FROM consolidation_step_proofs WHERE step_id=?',(step['id'],))}
                        self._new_step(batch_id,'lookup',request,lookup_proofs|inherited)
                    return dict(state='lookup_required',batch_id=batch_id,complete=False,failed=[],continuation_summary='',summary_withheld=True,next=self._prepared(batch,self._step(batch_id)))
                self._consume(step,value,usage)
            else:
                refs.update(json.loads(state['lookup_refs']));failed.update(json.loads(state['wire_failed']))
                failed.update(self._bind(value,json.loads(state['lookup_requests']),decoded))
                self._consume(step,value,usage)
            return self._finish(batch,reservation,sources,context,decoded,failed,summary,refs)
        except Exception as exc:
            self._consume(step,value,usage,failed=True);self.abort(batch_id,type(exc).__name__+':'+str(exc));raise

    def abort(self,batch_id,reason='model_unavailable'):
        with self.db:self.db.execute("UPDATE consolidation_steps SET state='failed',consumed_at=? WHERE batch_id=? AND state='prepared'",(time.time(),batch_id))
        LegacyScheduler.abort(self.base,batch_id,reason)

    def flush(self,session_id='default',*,reason='before_compact',retry_failed=True):
        if reason not in ['before_compact','before_reset','session_end','token_threshold']:raise ValueError('unsupported consolidation event')
        started=time.perf_counter();results=[];calls=0;failures=[];attempted=set();steps=0
        # Every extraction OR binding request consumes a loop slot. Persisted
        # prepared stages can resume in a later event without re-extraction.
        for _ in range(self.core.config.consolidation_max_batches):
            prepared=self.prepare(session_id,retry_failed=retry_failed,_skip_source_ids=attempted)
            if prepared['state']!='prepared':
                if prepared['state']!='empty':failures.append(prepared)
                if prepared['state']=='blocked' and prepared.get('source_id') not in attempted:
                    sid=prepared.get('source_id')
                    if sid:
                        attempted.add(sid)
                        if any(r['id'] not in attempted and self.base._visible(r) and r['state']=='pending' for r in self.base._rows(session_id)):continue
                break
            batch_id=prepared['batch_id'];request=prepared['request'];attempted.update(prepared['source_ids'])
            try:
                if prepared.get('stage','extract')=='extract' and all(s['role']=='assistant' for s in request['payload']['sources']):
                    value=dict(ok=True,items=[]) if prepared['wire_version']==4 else self.base._empty_response(request['payload']['sources'],prepared['wire_version']);usage=dict(model_calls=0)
                else:
                    calls+=1
                    out=self.core.extractor.call(request['system'],request['payload'],request['schema'],max_tokens=request['max_tokens'],source_id=batch_id,cache=False)
                    if out.get('done_reason') in ['length','max_tokens']:raise ValueError('truncated_batch_output')
                    value=out['value'];usage={k:out[k] for k in ['prompt_eval_count','eval_count','wall_ms','usage'] if k in out}
                    usage.update(model_calls=1,estimated_input_tokens=prepared['estimated_input_tokens'],token_counter=self.core.tokens.name)
                result=self.commit(batch_id,value,usage=usage) if prepared['wire_version']==4 else self.base.commit(batch_id,value,usage=usage)
                results.append(result);steps+=1
                failures.extend(result.get('failed',[]))
            except Exception as exc:
                self.abort(batch_id,type(exc).__name__+':'+str(exc));steps+=1
                failures.append(dict(state='failed',batch_id=batch_id,error=type(exc).__name__,reason=str(exc)[:300]))
        remaining=[r for r in self.base._rows(session_id) if self.base._visible(r) and r['state'] not in ['done','deleted','cancelled']]
        return dict(event=reason,session_id=session_id,complete=not remaining,pending_sources=len(remaining),
            failed_sources=sum(r['state']=='failed' for r in remaining),batches=results,model_calls=calls,processing_stage_slots=steps,
            failure=failures[0] if failures else None,failures=failures,can_compact=True,raw_retained=True,wall_ms=(time.perf_counter()-started)*1000)
