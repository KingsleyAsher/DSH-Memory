"""Wire-v2 scheduler: protected targets, evidence IDs and output reservation."""
import json
import re
import time
import uuid

from .consolidation import Consolidation as LegacyScheduler
from .atomic_wire import PROMPT, schema_for, source_packet, decode_isolated, estimate_output, target_candidates
from .contract import sha
from .policy import VALUE_FIELDS
from . import compact_wire


class Consolidation(LegacyScheduler):
    def __init__(self,core):
        super().__init__(core)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS consolidation_reservations(
          batch_id TEXT PRIMARY KEY,refs TEXT,context_ids TEXT,output_limit INTEGER,estimated_output INTEGER);
        CREATE TABLE IF NOT EXISTS consolidation_limits(
          session_id TEXT,project TEXT,entity TEXT,max_sources INTEGER,
          PRIMARY KEY(session_id,project,entity));
        ''')
        columns={r['name'] for r in self.db.execute('PRAGMA table_info(consolidation_reservations)')}
        if 'wire_version' not in columns:self.db.execute('ALTER TABLE consolidation_reservations ADD COLUMN wire_version INTEGER NOT NULL DEFAULT 2')
        if 'wire_map' not in columns:self.db.execute('ALTER TABLE consolidation_reservations ADD COLUMN wire_map TEXT')
        self.db.commit()

    def _budgets(self):
        declared=self.core.config.consolidation_context_tokens
        actual=getattr(self.core.extractor,'context_window',declared)
        if type(actual) is not int or actual<2048:raise ValueError('invalid extractor context capability')
        context=min(declared,actual)
        output=min(self.core.config.consolidation_output_tokens,max(512,int(context*.4)))
        input_cap=min(self.core.config.consolidation_input_tokens,context-output-256)
        return input_cap,output,context

    def _request(self,sources,context,targets,output):
        refs={};entries=[]
        for i,row in enumerate(targets,1):
            ref='T'+str(i);refs[ref]=row['id']
            entries.append(dict(ref=ref,source_id=row['source_id'],field=row['field'],topic=row.get('topic',''),
                                attribute=row.get('attribute') or row['field'],kind=row['kind'],
                                epistemic=row['epistemic'],value=row['value']))
        if self.core.config.consolidation_wire=='compact':
            return compact_wire.build_request(sources,context,entries,output),refs
        request=dict(system=PROMPT,payload=dict(scope=dict(project=sources[0]['project'],entity=sources[0]['entity']),
                     sources=[source_packet(s) for s in sources],
                     earlier_context=[{k:s[k] for k in ['id','seq','role','text']} for s in context],targets=entries),
                     schema=schema_for([s['id'] for s in sources]),max_tokens=output)
        return request,refs

    def _operations_pending(self,session_id=None):
        sql="SELECT 1 FROM consolidation_batches b JOIN consolidation_reservations r ON r.batch_id=b.id WHERE b.state='prepared' AND r.wire_version=4"
        args=()
        if session_id is not None:sql+=' AND b.session_id=?';args=(session_id,)
        return bool(self.db.execute(sql+' LIMIT 1',args).fetchone())

    def prepare(self,session_id='default',*,retry_failed=False,_skip_source_ids=(),_operation_bypass=False):
        if not _operation_bypass and (self.core.config.consolidation_wire=='operations' or self._operations_pending(session_id)):
            from .operation_consolidation import OperationEngine
            return OperationEngine(self).prepare(session_id,retry_failed=retry_failed,_skip_source_ids=_skip_source_ids)
        session_id=self.session(session_id);self._recover();input_cap,output_cap,context_cap=self._budgets()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE');rows=self._rows(session_id)
            if any(r['state']=='working' and self._visible(r) for r in rows):return dict(state='busy',session_id=session_id)
            eligible=[r for r in rows if self._visible(r) and r['state'] not in ['done','deleted','cancelled']]
            if not eligible:self._advance(session_id);return dict(state='empty',session_id=session_id)
            # A failed hole remains authoritative, but does not hold unrelated
            # later deltas hostage. One event attempts each source at most once.
            available=[r for r in eligible if r['id'] not in _skip_source_ids and
                       (r['state']!='failed' or (retry_failed and r['attempts']<self.core.config.max_extract_attempts))]
            if not available:return dict(state='blocked',source_id=eligible[0]['id'],reason='failed_delta_retained')
            first=available[0];source=json.loads(first['payload'])
            catalog=self.store.claim_catalog(source);catalog_ids={t['id'] for t in catalog};required_by_source={}
            limit=self.db.execute('SELECT max_sources FROM consolidation_limits WHERE session_id=? AND project=? AND entity=?',(session_id,source['project'],source['entity'])).fetchone()
            max_sources=min(self.core.config.consolidation_max_sources,limit[0] if limit else self.core.config.consolidation_max_sources)
            selected=[];final=None;final_refs={};final_context=[];estimated=0;blocked_reason=None
            for row in available:
                s=json.loads(row['payload'])
                if (s['project'],s['entity'])!=(source['project'],source['entity']):break
                candidate=selected+[s];need=estimate_output(candidate,self.core.tokens.count)
                if need>output_cap:break
                # Shared targets may only contain knowledge predating the first
                # source. A later delta needing an intermediate archived target
                # must start a separate batch, never expose it to an old hole.
                source_catalog=self.store.claim_catalog(s)
                required_by_source[s['id']]={r['target_id'] for r in self.store._pending_reminder_rows(s['seq'],s['id'])}
                local,local_protected=target_candidates(source_catalog,[s],required_by_source=required_by_source)
                required={t['id'] for t in local[:local_protected]} | required_by_source[s['id']]
                if required-catalog_ids:
                    if not selected:blocked_reason='required_target_not_visible'
                    break
                targets,protected=target_candidates(catalog,candidate,required_by_source=required_by_source)
                contexts,required_context=self._context_plan(candidate)
                if required_context-({c['id'] for c in contexts}|{c['id'] for c in candidate}):
                    if not selected:blocked_reason='required_context_not_visible'
                    break
                request,refs=self._request(candidate,contexts,targets,output_cap)
                while len(targets)>protected and self.core.tokens.count(request)>input_cap:
                    targets.pop();request,refs=self._request(candidate,contexts,targets,output_cap)
                # Protect evidence for every source, including a later user in
                # this candidate batch. Prefer relevant originals over recent
                # unrelated context; never cut a whole-source quotation.
                while self.core.tokens.count(request)>input_cap and self._drop_optional_context(contexts,required_context,candidate):
                    request,refs=self._request(candidate,contexts,targets,output_cap)
                if self.core.tokens.count(request)>input_cap:
                    if not selected and required_context:blocked_reason='required_context_input_budget'
                    break
                selected=candidate;final=request;final_refs=refs;final_context=contexts;estimated=need
                if len(selected)>=max_sources:break
            if not selected:
                self.db.execute("UPDATE inbox SET state='failed',error='atomic_input_or_output_budget',attempts=attempts+1 WHERE id=?",(first['id'],))
                return dict(state='blocked',source_id=first['id'],reason=blocked_reason or 'oversize_source_or_required_context_retained')
            batch_id='compact-'+uuid.uuid4().hex;lease=time.time()+300;ids=[s['id'] for s in selected]
            self.db.execute('INSERT INTO consolidation_batches VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                            (batch_id,session_id,source['project'],source['entity'],json.dumps(ids),'prepared',lease,
                             sha(json.dumps(final,ensure_ascii=False,sort_keys=True)),None,'{}',None))
            wire=3 if self.core.config.consolidation_wire=='compact' else 2
            wire_map=compact_wire.handles_for(selected,final_context) if wire==3 else None
            self.db.execute('''INSERT INTO consolidation_reservations
                (batch_id,refs,context_ids,output_limit,estimated_output,wire_version,wire_map) VALUES(?,?,?,?,?,?,?)''',
                (batch_id,json.dumps(final_refs),json.dumps([s['id'] for s in final_context]),output_cap,estimated,wire,json.dumps(wire_map)))
            for sid in ids:self.db.execute("UPDATE inbox SET state='working',attempts=attempts+1,lease_until=?,error=NULL WHERE id=?",(lease,sid))
            return dict(state='prepared',batch_id=batch_id,session_id=session_id,source_ids=ids,
                        estimated_input_tokens=self.core.tokens.count(final),estimated_output_tokens=estimated,
                        output_limit=output_cap,context_limit=context_cap,summary_scope='batch_delta',wire_version=wire,request=final)

    def _empty_response(self,sources,wire_version=2):
        if wire_version==3:return dict(ok=True,items=[])
        return dict(complete=True,continuation_summary='',items=[dict(source_id=s['id'],facts=[],points=[],state=dict(actions=[],retractions=[])) for s in sources])

    def abort(self,batch_id,reason='model_unavailable'):
        reserved=self.db.execute('SELECT wire_version FROM consolidation_reservations WHERE batch_id=?',(batch_id,)).fetchone()
        if reserved and reserved['wire_version']==4:
            from .operation_consolidation import OperationEngine
            return OperationEngine(self).abort(batch_id,reason)
        row=self.db.execute('SELECT * FROM consolidation_batches WHERE id=?',(batch_id,)).fetchone()
        if row and row['state']=='prepared' and any(key in reason for key in ['output_budget','truncated','incomplete_atomic']):
            smaller=max(1,len(json.loads(row['source_ids']))//2)
            with self.db:
                previous=self.db.execute('SELECT max_sources FROM consolidation_limits WHERE session_id=? AND project=? AND entity=?',(row['session_id'],row['project'],row['entity'])).fetchone()
                self.db.execute('INSERT OR REPLACE INTO consolidation_limits VALUES(?,?,?,?)',
                                (row['session_id'],row['project'],row['entity'],min(smaller,previous[0]) if previous else smaller))
        super().abort(batch_id,reason)

    def commit(self,batch_id,value,*,usage=None):
        reserved=self.db.execute('SELECT wire_version FROM consolidation_reservations WHERE batch_id=?',(batch_id,)).fetchone()
        if reserved and reserved['wire_version']==4:
            from .operation_consolidation import OperationEngine
            return OperationEngine(self).commit(batch_id,value,usage=usage)
        batch=self.db.execute('SELECT * FROM consolidation_batches WHERE id=?',(batch_id,)).fetchone()
        if not batch:raise ValueError('unknown batch')
        if batch['state']=='committed':
            failed=json.loads(batch['error']) if batch['error'] else []
            return dict(state='already_committed',batch_id=batch_id,model_calls=0,complete=not failed,failed=failed)
        if batch['state']!='prepared':raise ValueError('batch no longer prepared')
        try:
            reservation=self.db.execute('SELECT * FROM consolidation_reservations WHERE batch_id=?',(batch_id,)).fetchone()
            if not reservation:raise ValueError('missing atomic reservation')
            measured=self.core.tokens.count(value)
            if measured>reservation['output_limit']:raise ValueError('atomic_output_budget_exceeded')
            sources=[]
            for sid in json.loads(batch['source_ids']):
                r=self.db.execute('SELECT * FROM inbox WHERE id=?',(sid,)).fetchone()
                if not r or not self.store.visible_source(sid) or r['state']!='working' or r['lease_until']!=batch['lease_until'] or batch['lease_until']<time.time():raise ValueError('batch_source_changed_or_lease_expired')
                sources.append(json.loads(r['payload']))
            context=[]
            for sid in json.loads(reservation['context_ids']):
                r=self.db.execute('SELECT payload FROM inbox WHERE id=?',(sid,)).fetchone()
                if not r or not self.store.visible_source(sid):raise ValueError('atomic_context_changed')
                context.append(json.loads(r['payload']))
            wire=reservation['wire_version'];wire_failed={}
            if wire==3:value,wire_failed=compact_wire.expand_response(value,sources,context,json.loads(reservation['wire_map']))
            elif wire!=2:raise ValueError('unknown_reserved_wire_version')
            decoded,decode_failed=decode_isolated(value,sources,context)
            decode_failed.update(wire_failed)
            refs=json.loads(reservation['refs']);done=[];failed=[]
            def resolve(ref,current):
                if ref in refs:return refs[ref]
                match=re.fullmatch(r'(.+)#([FL])(\d+)',ref)
                if not match:raise ValueError('unknown_atomic_target_ref')
                sid,kind,ordinal=match.groups();earlier=next((s for s in sources if s['id']==sid and s['seq']<current['seq']),None)
                if not earlier:raise ValueError('atomic_target_is_future_or_outside_batch')
                state=self.db.execute('SELECT state FROM inbox WHERE id=?',(sid,)).fetchone()
                if not state or state['state']!='done':raise ValueError('atomic_dependency_source_not_done:'+sid)
                result=self.store.claim_by_ref(sid,int(ordinal),'fact' if kind=='F' else 'linked')
                if isinstance(result,dict):result=result['id']
                if not result:raise ValueError('atomic_target_not_durable')
                return result
            for source in sources:
                sid=source['id']
                try:
                    if sid in decode_failed:
                        detail=decode_failed[sid]
                        raise ValueError(detail['error']+':'+detail['reason'])
                    result=decoded[sid]
                    for spec in result['claim_specs']+result['linked_specs']:
                        spec['replace_ids']=[resolve(x,source) for x in spec.pop('replace_refs')]
                    result['retract_claims']=[dict(id=resolve(c['ref'],source),quote=c['quote']) for c in result['retract_claims']]
                    self._check_configuration_order(source,result)
                    state=self.store.finish_atomic(source,result,linked_context=context+sources,strict=True)
                    done.append(dict(id=sid,state=state,facts=len(result['facts']),session_points=len(result['session_points']),diagnostics=result['diagnostics']))
                except (ValueError,TypeError,KeyError) as exc:
                    detail=dict(id=sid,state='failed',error=type(exc).__name__,reason=str(exc)[:300])
                    self.store.fail(source,detail['error']+':'+detail['reason']);failed.append(detail)
            info=dict(usage or {},estimated_output_tokens=measured,output_limit=reservation['output_limit'])
            summary=value['continuation_summary'] if not failed else None
            with self.db:
                self.db.execute("UPDATE consolidation_batches SET state='committed',summary=?,usage=?,error=? WHERE id=?",(summary,json.dumps(info),json.dumps(failed,ensure_ascii=False) if failed else None,batch_id));self._advance(batch['session_id'])
            return dict(state='committed',batch_id=batch_id,complete=not failed,done=done,failed=failed,
                        continuation_summary=summary or '',summary_withheld=bool(failed),summary_scope='batch_delta',wire_version=wire,output_tokens=measured,output_limit=reservation['output_limit'])
        except Exception as exc:
            self.abort(batch_id,type(exc).__name__+':'+str(exc));raise

    def _check_configuration_order(self,source,result):
        """Fail closed on delayed scalar replay; never let an old retry win."""
        fields=({f['field'] for f in result['facts'] if f['kind']=='fact' and f['field'] in VALUE_FIELDS}
                | {field for field,action in result['semantic_actions'].items() if action in ['set','pending']})
        if not fields:return
        later=self.db.execute('''SELECT s.id,s.proposal FROM sources s JOIN controls c ON c.source_id=s.id
            WHERE s.project=? AND s.entity=? AND s.seq>? AND c.excluded=0 AND c.deleted=0 AND c.withdrawn_at IS NULL''',
            (source['project'],source['entity'],source['seq'])).fetchall()
        for row in later:
            proposal=json.loads(row['proposal'] or '{}')
            touched=({f.get('field') for f in proposal.get('facts',[]) if f.get('kind')=='fact'}
                     | set(proposal.get('semantic_actions',{})))
            if fields&touched:raise ValueError('atomic_late_configuration_requires_review:'+','.join(sorted(fields&touched)))

    def flush(self,session_id='default',*,reason='before_compact',retry_failed=True):
        if self.core.config.consolidation_wire=='operations' or self._operations_pending(session_id):
            from .operation_consolidation import OperationEngine
            return OperationEngine(self).flush(session_id,reason=reason,retry_failed=retry_failed)
        if reason not in ['before_compact','before_reset','session_end','token_threshold']:raise ValueError('unsupported consolidation event')
        started=time.perf_counter();results=[];calls=0;failures=[];attempted=set()
        for _ in range(self.core.config.consolidation_max_batches):
            prepared=self.prepare(session_id,retry_failed=retry_failed,_skip_source_ids=attempted)
            if prepared['state']!='prepared':
                if prepared['state']!='empty' and not failures:failures.append(prepared)
                # Budget failures can be skipped on this event, too; they retain
                # their raw source and attempt count, while a later delta runs.
                if prepared['state']=='blocked' and prepared.get('source_id') not in attempted:
                    sid=prepared.get('source_id')
                    if sid:
                        attempted.add(sid)
                        if any(r['id'] not in attempted and self._visible(r) and r['state']=='pending' for r in self._rows(session_id)):continue
                break
            attempted.update(prepared['source_ids']);batch_id=prepared['batch_id'];request=prepared['request']
            try:
                if all(s['role']=='assistant' for s in request['payload']['sources']):
                    value=self._empty_response(request['payload']['sources'],prepared['wire_version']);usage=dict(model_calls=0)
                else:
                    calls+=1
                    out=self.core.extractor.call(request['system'],request['payload'],request['schema'],max_tokens=request['max_tokens'],source_id=batch_id,cache=False)
                    if out.get('done_reason') in ['length','max_tokens']:raise ValueError('truncated_batch_output')
                    value=out['value'];usage={k:out[k] for k in ['prompt_eval_count','eval_count','wall_ms','usage'] if k in out}
                    usage.update(model_calls=1,estimated_input_tokens=prepared['estimated_input_tokens'],token_counter=self.core.tokens.name)
                result=self.commit(batch_id,value,usage=usage);results.append(result)
                failures.extend(result['failed'])
            except Exception as exc:
                self.abort(batch_id,type(exc).__name__+':'+str(exc))
                failures.append(dict(state='failed',batch_id=batch_id,error=type(exc).__name__,reason=str(exc)[:300]))
        remaining=[r for r in self._rows(session_id) if self._visible(r) and r['state'] not in ['done','deleted','cancelled']]
        return dict(event=reason,session_id=session_id,complete=not remaining,pending_sources=len(remaining),
                    failed_sources=sum(r['state']=='failed' for r in remaining),batches=results,model_calls=calls,
                    failure=failures[0] if failures else None,failures=failures,
                    can_compact=True,raw_retained=True,wall_ms=(time.perf_counter()-started)*1000)
