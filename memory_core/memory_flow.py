"""One source-bound commit path for proactive tools and shared compaction.

No language calls here: the host supplies the current turn/compaction response.
Explicit-constraint coverage is conservative and separate from source 'done'.
"""
import copy
import json
import re
import uuid

from . import compact_wire,operation_wire
from .atomic_wire import segments
from .contract import sha
from .tool_memory import ToolMemory,encoded


def clean_text(text):return re.sub(r'[\W_]+','',text)


def obligations(source):
    if source['role']!='user':return []
    result=[]
    for segment in segments(source):
        for match in re.finditer(r'[^，,。；;！？!?\n]+[！？?]?',segment['text']):
            text=match.group().strip()
            if len(text)<6 or not re.search('不要|不能|不应|必须|不想|不希望|希望|尽量|避免|记住|更正|撤回|暂缓|尚未|还没|未创建|不再|不是要|而不是|不等于|会把.{0,12}(?:带偏|带歪)|固定(?:修法|结论)',text):continue
            offset=segment['start']+match.start()
            result.append(dict(id='O'+sha(source['id']+sha(source['text'])+str(offset))[:12],source_id=source['id'],
                segment=segment['id'],text=text,hard=not bool(re.search('[？?]|示例|假设|比如|这顿|本顿',text))))
    return result


def invalidate_flow(store,sid,redact=False):
    if not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_flow_proofs'").fetchone():return
    for row in store.db.execute('SELECT batch_id FROM memory_flow_proofs WHERE source_id=?',(sid,)).fetchall():
        # Any proof change invalidates persisted model context; deletion also
        # cannot leave quotations embedded in a cached request/summary.
        store.db.execute("UPDATE memory_flow_batches SET state='invalidated',request='{}',response=NULL,result=NULL WHERE id=?",(row[0],))
    store.db.execute("UPDATE memory_flow_coverage SET state='invalidated' WHERE source_id=?",(sid,))
    if redact:store.db.execute("UPDATE memory_flow_coverage SET text='' WHERE source_id=?",(sid,))


class MemoryFlow:
    def __init__(self,core):
        self.core=core;self.tools=ToolMemory(core);self.store=core.store;self.db=core.store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS memory_flow_batches(
          id TEXT PRIMARY KEY,mode TEXT,session_id TEXT,state TEXT,request TEXT,
          bindings TEXT,snapshots TEXT,response_hash TEXT,response TEXT,result TEXT);
        CREATE TABLE IF NOT EXISTS memory_flow_proofs(batch_id TEXT,source_id TEXT,PRIMARY KEY(batch_id,source_id));
        CREATE TABLE IF NOT EXISTS memory_flow_coverage(
          id TEXT PRIMARY KEY,source_id TEXT,source_sha TEXT,segment TEXT,text TEXT,hard INTEGER,state TEXT,reason TEXT);
        ''');self.db.commit()

    def ingest(self,source):
        result=self.tools.ingest(source);self._sync_coverage(self.tools._source(source['id']));return result

    def _sync_coverage(self,source):
        with self.db:
            for item in obligations(source):
                self.db.execute("INSERT OR IGNORE INTO memory_flow_coverage VALUES(?,?,?,?,?,?,'pending',NULL)",
                    (item['id'],source['id'],sha(source['text']),item['segment'],item['text'],int(item['hard'])))
                self.db.execute("UPDATE memory_flow_coverage SET state='pending',text=? WHERE id=? AND state='invalidated'",(item['text'],item['id']))
            self._refresh_coverage(source['id'])
            if self.db.execute("SELECT 1 FROM memory_flow_coverage WHERE source_id=? AND state='pending' LIMIT 1",(source['id'],)).fetchone():
                self.db.execute("UPDATE tool_memory_reviews SET state='pending' WHERE source_id=?",(source['id'],))

    def _refresh_coverage(self,sid):
        source=self.tools._source(sid)
        proposal=self.db.execute('SELECT proposal FROM sources WHERE id=?',(sid,)).fetchone()
        p=json.loads(proposal[0]) if proposal else {}
        bodies=[x['value_text'] for x in p.get('facts',[]) if x.get('kind')=='fact']
        bodies += [x['statement'] for x in p.get('linked_points',[])]
        # Operation quotations themselves are stored evidence, including a pure
        # withdrawal that has no new fact body. The guard never counts an
        # arbitrary full source/quote as memory coverage.
        bodies += [json.loads(r[0])['quote'] for r in self.db.execute('SELECT detail FROM claim_operation_audit WHERE source_id=?',(sid,)) if json.loads(r[0])['action'] in ['retract','retain']]
        for row in self.db.execute("SELECT * FROM memory_flow_coverage WHERE source_id=? AND source_sha=? AND state='pending'",(sid,sha(source['text']))).fetchall():
            if any(clean_text(row['text']) in clean_text(body) for body in bodies):
                self.db.execute("UPDATE memory_flow_coverage SET state='covered',reason='stored_body' WHERE id=?",(row['id'],))

    def prepare(self,mode,session_id='default',*,source_ids=None,context_ids=None,history_refs=None):
        if mode not in ['active','compaction']:raise ValueError('invalid_memory_flow_mode')
        rows=self.db.execute('SELECT payload FROM inbox WHERE session_id=? ORDER BY seq',(session_id,)).fetchall()
        dialogue=[s for r in rows if (s:=json.loads(r[0])) and self.store.visible_source(s['id'])]
        if context_ids is not None:
            wanted=set(context_ids)
            dialogue=[s for s in dialogue if s['id'] in wanted]
            if wanted!={s['id'] for s in dialogue}:raise ValueError('context_outside_visible_session')
        if not dialogue:return dict(state='empty')
        authored=[s for s in dialogue if s['role']!='assistant' and (source_ids is None or s['id'] in source_ids)]
        if source_ids is not None and set(source_ids)!={s['id'] for s in authored}:raise ValueError('source_outside_visible_session')
        if not authored or len(authored)>24:raise ValueError('memory_flow_source_budget')
        for s in authored:self._sync_coverage(s)
        by_id={s['id']:s for s in dialogue};proofs={s['id']:s for s in dialogue}
        handles={'S'+str(i+1):s['id'] for i,s in enumerate(dialogue)};inverse={v:k for k,v in handles.items()}
        scopes=[];packets=[]
        for s in dialogue:
            scope=[s['project'],s['entity']]
            if scope not in scopes:scopes.append(scope)
            packets.append(dict(id=inverse[s['id']],scope=scopes.index(scope),role=s['role'],segments=[x['text'] for x in segments(s)]))
        catalog={};allowed={};existing={}
        for s in authored:
            own=self.store.claim_catalog(s);allowed[inverse[s['id']]]=[r['id'] for r in own]
            for r in own:
                catalog[r['id']]=r
                for pid in [r['source_id']]+r.get('source_ids',[]):
                    if pid not in proofs:proofs[pid]=self.tools._source(pid)
            old=self.db.execute('SELECT proposal FROM sources WHERE id=?',(s['id'],)).fetchone()
            p=json.loads(old[0]) if old else {}
            existing[inverse[s['id']]]=[x['value_text'] for x in p.get('facts',[])]+[x['statement'] for x in p.get('linked_points',[])]
        targets={'T'+str(i+1):cid for i,cid in enumerate(catalog)};target_inverse={cid:k for k,cid in targets.items()}
        allowed={h:[target_inverse[cid] for cid in ids] for h,ids in allowed.items()}
        required=[inverse[s['id']] for s in authored]
        anchors=[]
        with self.db:
            for s in authored:
                self._refresh_coverage(s['id'])
                for r in self.db.execute("SELECT * FROM memory_flow_coverage WHERE source_id=? AND state='pending'",(s['id'],)):
                    anchors.append(dict(id=r['id'],source=inverse[s['id']],segment=int(r['segment'][1:]),text=r['text'],hard=bool(r['hard'])))
        schema=operation_wire.schema_for(required)
        # Handles are enum-checked both in structured output and at commit.
        item=schema['properties']['items']['items']
        item['properties']['p']['items']['properties']['e']['items']['properties']['id']['enum']=list(handles)
        memory_schema=compact_wire.obj(dict(items=schema['properties']['items'],skips=dict(type='array',items=compact_wire.obj(dict(anchor=dict(type='string',enum=[a['id'] for a in anchors]) if anchors else dict(type='string'),reason=dict(type='string',enum=['question','example','temporary'])),['anchor','reason']))),['items','skips'])
        response_schema=compact_wire.obj(dict(continuation_summary=dict(type='string'),memory=memory_schema),['continuation_summary','memory']) if mode=='compaction' else memory_schema
        system=operation_wire.PROMPT+'''\n来源及旧目标只用程序发出的S/T句柄，不输出或拼接原始ID。p.e.id也只能用S句柄。同批较早目标可S句柄#F0/#L0。existing仅用于去重，已存一点不代表整源覆盖。
不得只保存“这两句、它们”等缺对象指代；需要前文才能自足时用p补全对象并引用双源。用户禁止声称执行成功时，应保留是否有可验证工具回执的证据边界；只能按本批证据说未提供回执，不能推成现实中绝未执行。若需前文助手状态才能完整表达，使用p保留归因和用户限制，不伪造逐字事实。
obligations是原文中容易漏掉的明确要求；保存这些限制的完整原句或可自足的单属性断言，不能仅引用它却省掉内容/对象/条件。用户简称采纳必须联同前文保留修饰词，例如可重复使用。拒绝/暂缓与未执行边界须保存。skips只用于原文明确的提问、示例或当顿临时内容，不能跳过hard约束。每个压缩来源都返回item（无新点可o=[]），主动提交可只给有新点的来源。只输出本次schema。'''
        if mode=='compaction':system+='\n你正在同一次上下文压缩调用中生成续聊摘要和记忆。continuation_summary概括当前任务、未完成事项、纠错及证据边界，memory只给增量。不得另发提炼请求。'
        request=dict(system=system,payload=dict(scopes=scopes,messages=packets,write_sources=required,existing=existing,targets=[operation_wire.target_packet(catalog[cid],h) for h,cid in targets.items()],allowed_targets=allowed,obligations=anchors),schema=response_schema,max_tokens=self.core.config.consolidation_output_tokens)
        if history_refs is not None:
            # The host already supplies these immutable messages in its normal
            # conversation/compaction prefix. Send only identity and character
            # spans, never a second copy of that history in memory instructions.
            for packet,s in zip(packets,dialogue):
                if s['id'] not in history_refs:raise ValueError('missing_host_history_reference')
                if history_refs[s['id']] is None:continue
                packet['message_id']=history_refs[s['id']]
                packet['segments']=[dict(n=i+1,start=x['start'],end=x['start']+len(x['text'])) for i,x in enumerate(segments(s))]
            request['system']+='\nmessages仅标注现有对话消息的message_id及正文字符段[start,end)，不是新原文。e使用对应段的n（从1开始）；内容从本次已提供的原始history取，不重复读取另一份全文。'
        if self.core.tokens.count(request)>self.core.config.consolidation_input_tokens:raise ValueError('memory_flow_input_budget')
        bindings=dict(sources=handles,targets=targets,write_sources=required,anchors=[a['id'] for a in anchors])
        snapshots={sid:dict(sha=sha(s['text']),seq=s['seq'],project=s['project'],entity=s['entity'],role=s['role'],session_id=s.get('session_id','default')) for sid,s in proofs.items()}
        bid='flow-'+uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO memory_flow_batches VALUES(?,?,?,'prepared',?,?,?,NULL,NULL,NULL)",(bid,mode,session_id,encoded(request),encoded(bindings),encoded(snapshots)))
            for sid in proofs:self.db.execute('INSERT INTO memory_flow_proofs VALUES(?,?)',(bid,sid))
        out=dict(state='prepared',batch_id=bid,mode=mode,request=request,estimated_input_tokens=self.core.tokens.count(request),anchors=len(anchors))
        if mode=='active':out['tool']=dict(name='memory_submit',description='提交本轮值得记忆的增量；程序校验来源、状态及版本，不需要用户逐项确认。',inputSchema=compact_wire.obj(dict(batch_id=dict(type='string',enum=[bid]),memory=memory_schema),['batch_id','memory']))
        return out

    def submit_tool(self,arguments):
        if not isinstance(arguments,dict) or set(arguments)!={'batch_id','memory'}:raise ValueError('memory_submit_arguments')
        row=self.db.execute('SELECT mode FROM memory_flow_batches WHERE id=?',(arguments['batch_id'],)).fetchone()
        if not row or row['mode']!='active':raise ValueError('not_an_active_memory_tool_batch')
        return self.commit(arguments['batch_id'],arguments['memory'])

    def _repair_literal_transport(self, item, source):
        """Only restore the exact cited span when punctuation/spacing alone differs.

        Never fuzzy-match words, digits, negation, symbols or linked assertions.
        The original model response remains stored unchanged in the batch.
        """
        repairs=[]
        def literal(s):
            # Numeric punctuation and signs can change values (1.5, -1).
            ignored='' if any(c.isdigit() for c in s) else '，,。；;！？!?'
            return ''.join(c for c in s if not c.isspace() and c not in ignored)
        for record in item.get('f',[]):
            if not isinstance(record,dict) or not isinstance(record.get('v'),str):continue
            quote=compact_wire._quote(source,record.get('e'))
            if record['v'] not in quote and literal(record['v']) and literal(record['v'])==literal(quote):
                record['v']=quote;repairs.append('restored_exact_cited_span')
        # A single unbound assert and a single unbound record are unambiguous.
        ops=item.get('o',[])
        used={o.get('n') for o in ops if isinstance(o,dict)}
        records=[k+str(i) for field,k in [('f','F'),('p','L')] for i,_ in enumerate(item.get(field,[])) if k+str(i) not in used]
        missing=[o for o in ops if isinstance(o,dict) and o.get('op')=='assert' and not o.get('n')]
        if len(records)==len(missing)==1 and not missing[0].get('t') and not missing[0].get('q'):
            missing[0]['n']=records[0];repairs.append('bound_single_assert_record')
        return repairs

    def commit(self,batch_id,value):
        row=self.db.execute('SELECT * FROM memory_flow_batches WHERE id=?',(batch_id,)).fetchone()
        if not row:raise ValueError('unknown_memory_flow_batch')
        if row['state']=='invalidated':raise ValueError('memory_flow_proof_changed')
        digest=sha(encoded(value))
        if row['response_hash'] and row['response_hash']!=digest:raise ValueError('memory_flow_first_response_changed')
        if row['state']=='committed':return json.loads(row['result'])
        snapshots=json.loads(row['snapshots']);bindings=json.loads(row['bindings']);request=json.loads(row['request'])
        for sid,expected in snapshots.items():
            s=self.tools._source(sid)
            if sha(s['text'])!=expected['sha'] or any(s.get(k)!=expected[k] for k in ['seq','project','entity','role','session_id']):raise ValueError('memory_flow_snapshot_changed')
        if self.core.tokens.count(value)>request['max_tokens']:raise ValueError('memory_flow_output_budget')
        if row['mode']=='compaction':
            if not isinstance(value,dict) or set(value)!={'continuation_summary','memory'} or not isinstance(value['continuation_summary'],str):raise ValueError('shared_compaction_shape')
            body=value['memory'];summary=value['continuation_summary']
        else:body=value;summary=None
        if not isinstance(body,dict) or set(body)!={'items','skips'} or not isinstance(body['items'],list):raise ValueError('memory_flow_response_shape')
        named=[x.get('id') for x in body['items'] if isinstance(x,dict)]
        if len(named)!=len(body['items']) or len(set(named))!=len(named):raise ValueError('memory_flow_duplicate_source')
        if any(h not in bindings['write_sources'] for h in named):raise ValueError('source_handle_not_reserved')
        if row['mode']=='compaction' and set(named)!=set(bindings['write_sources']):raise ValueError('shared_compaction_source_coverage')
        if not isinstance(body['skips'],list):raise ValueError('coverage_skip_shape')
        for skip in body['skips']:
            if not isinstance(skip,dict) or set(skip)!={'anchor','reason'} or skip['anchor'] not in bindings['anchors'] or skip['reason'] not in ['question','example','temporary']:raise ValueError('coverage_skip_not_reserved')
        # Persist the first actual model response before local dispatch. After a
        # crash, the same response resumes with existing per-source receipts.
        with self.db:self.db.execute('UPDATE memory_flow_batches SET response_hash=?,response=? WHERE id=?',(digest,encoded(value),batch_id))
        results=[]
        for raw in sorted(body['items'],key=lambda x:self.tools._source(bindings['sources'][x['id']])['seq']):
            item=copy.deepcopy(raw);sid=bindings['sources'][item['id']];item['id']=sid
            try:
                for p in item.get('p',[]):
                    for e in p['e']:
                        if e['id'] not in bindings['sources']:raise ValueError('proof_handle_not_reserved')
                        e['id']=bindings['sources'][e['id']]
                for op in item.get('o',[]):
                    refs=[]
                    for ref in op.get('t',[]):
                        if ref in bindings['targets']:refs.append(bindings['targets'][ref])
                        else:
                            head,sep,tail=ref.partition('#')
                            if not sep or head not in bindings['sources'] or not re.fullmatch('[FL][0-9]+',tail):raise ValueError('target_handle_not_reserved')
                            refs.append(bindings['sources'][head]+'#'+tail)
                    op['t']=refs
                repairs=self._repair_literal_transport(item,self.tools._source(sid))
                receipt=self.tools.write(batch_id+':'+sid,item,reviewed=False)
                if repairs:receipt=dict(receipt,transport_repairs=repairs)
                results.append(receipt)
            except (ValueError,KeyError,TypeError) as exc:results.append(dict(state='rejected',source_id=sid,reason=str(exc)[:500]))
        with self.db:
            for skip in body['skips']:
                if set(skip)!={'anchor','reason'} or skip['anchor'] not in bindings['anchors']:raise ValueError('coverage_skip_not_reserved')
                anchor=self.db.execute('SELECT * FROM memory_flow_coverage WHERE id=?',(skip['anchor'],)).fetchone()
                allowed=(not anchor['hard'] and ((skip['reason']=='question' and re.search('[？?]',anchor['text'])) or (skip['reason']=='example' and re.search('示例|假设|比如',anchor['text'])) or (skip['reason']=='temporary' and re.search('本顿|这顿',anchor['text']))))
                if allowed:self.db.execute("UPDATE memory_flow_coverage SET state='skipped',reason=? WHERE id=?",(skip['reason'],skip['anchor']))
            for h in named:self._refresh_coverage(bindings['sources'][h])
            done=[];pending=[]
            for h in bindings['write_sources']:
                sid=bindings['sources'][h]
                gaps=self.db.execute("SELECT COUNT(*) FROM memory_flow_coverage WHERE source_id=? AND state='pending'",(sid,)).fetchone()[0]
                saved=any(r['source_id']==sid and r['state']=='saved' for r in results)
                if row['mode']=='compaction' and saved and not gaps:
                    self.db.execute("UPDATE tool_memory_reviews SET state='done' WHERE source_id=?",(sid,));done.append(sid)
                else:pending.append(sid)
            out=dict(state='committed',mode=row['mode'],results=results,coverage_done=done,coverage_pending=pending,
                     memory_complete=not pending and all(r['state']=='saved' for r in results),coverage_scope='batch',model_calls=0,raw_retained=True)
            if row['mode']=='active':
                good=[r for r in results if r['state']=='saved']
                failed=[r for r in results if r['state']!='saved']
                stored=sum(r.get('facts',0)+r.get('linked',0)+r.get('duplicate_records',0) for r in good)
                changed=any(r.get('operations',0) for r in good)
                confirmed=bool(good) and not failed and bool(stored or changed)
                out.update(state='saved' if confirmed else 'partial' if good and failed else 'not_saved',
                    transaction_state='committed',can_confirm_saved=confirmed,saved_records=stored,
                    message='本次提交已保存，可按具体条目确认；未提交来源仍待检查。' if confirmed else
                    '本次记忆未完整保存，禁止声称已记住。根据results修正后使用下一步新batch_id重试；原文已保留。',
                    repair_hints=dict(fact_provenance='f.v必须逐字摘取e引用的原文，不能润色；需要整句时保留原标点。',
                        operation_record_required='assert/replace必须设置n，例如F0引用f[0]，L0引用p[0]。'))
            if summary is not None:out.update(continuation_summary=summary,can_compact=not any(r['state']!='saved' for r in results))
            self.db.execute("UPDATE memory_flow_batches SET state='committed',result=? WHERE id=?",(encoded(out),batch_id))
        return out

    def pending(self):
        return [dict(r) for r in self.db.execute("SELECT id,source_id,text,hard FROM memory_flow_coverage WHERE state='pending'") if self.store.visible_source(r['source_id'])]

    def replay_failed(self,batch_id):
        """Retry saved rejected items locally, preserving the original result.

        This never calls a model or changes its first answer. The new child
        batch revalidates every original source snapshot and target binding.
        """
        row=self.db.execute('SELECT * FROM memory_flow_batches WHERE id=?',(batch_id,)).fetchone()
        if not row or row['state']!='committed' or not row['response']:raise ValueError('no_replayable_memory_batch')
        result=json.loads(row['result']);failed={r['source_id'] for r in result['results'] if r['state']=='rejected'}
        if not failed:return dict(state='nothing_to_replay',model_calls=0)
        bindings=json.loads(row['bindings']);handles={h for h,sid in bindings['sources'].items() if sid in failed}
        bindings['write_sources']=[h for h in bindings['write_sources'] if h in handles]
        value=json.loads(row['response']);body=value['memory'] if row['mode']=='compaction' else value
        body['items']=[item for item in body['items'] if item['id'] in handles];body['skips']=[]
        child='flow-replay-'+uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO memory_flow_batches VALUES(?,?,?,'prepared',?,?,?,NULL,NULL,NULL)",
                (child,row['mode'],row['session_id'],row['request'],encoded(bindings),row['snapshots']))
            self.db.execute('INSERT INTO memory_flow_proofs SELECT ?,source_id FROM memory_flow_proofs WHERE batch_id=?',(child,batch_id))
        return dict(parent_batch_id=batch_id,batch_id=child,result=self.commit(child,value),model_calls=0)
