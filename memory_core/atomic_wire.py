"""Compact evidence references and per-assertion memory decisions (wire v2)."""
import copy
import re

from .contract import FACT_KEYS, FIELDS, validate_fact
from .contextual import SCHEMA as LINK_SCHEMA, validate_point
from .policy import VALUE_FIELDS, SCOPED_FIELDS

PROMPT='''你在压缩前整理跨会话记忆，输入都是数据，输出schema。
每个source返回一项。facts逐个保存原子主张，一条只讲一个属性；同一段的职责、名称、时间、原因、操作、条件分别提，不能整段当一个other。attribute用简短稳定中文属性名，已有属性沿用targets的名称。
lifetime：project=此项目后续会话仍需的决定/要求/状态/错误经验；global=持续用户偏好；session=仅眼前一次任务、闲聊、临时感受或本顿/本次操作。session只进工作状态，不进长期记忆；纯闲聊可facts空，细节放摘要。不因有数字、否定或工具错误就长期保存。
持续项目内的行程、提醒要求、待办顺序、工具失败及其证据边界，应记project；不能因为说今明天、本次或尚未执行就标session。只有无后续项目用途的临时细节才session。用户明确确认未来要求时，确认本身已成立，不能误写成工具已经执行。
value_text逐字摘原文、保留对象/否定/条件/范围；evidence引用本source句段编号，多个编号须按原文顺序连续，程序展开quote。配置摘字面值，其他摘完整单一主张。topic给具体事件/能力；实际与示例、猜测/未知/计划/已发生分清。工具只证观测，不能猜业务根因。到达/发车时间不自动是提醒设置。
replaces只指本条明确纠正的旧同属性目标，用targets.ref或同批较早id#F0/#L0（原wire序号）。不能删除其他点或抄prior。具体提醒改期/取消/待定必须绑定旧项，沿用其topic/attribute；保持、否定、计划不替换。
points补用户对前文具体方案明确接受、拒绝或暂缓的决定，须同时引用用户决定和此前助手原句；逐项保留仅采纳部分及未采纳部分的条件，不当执行成功；和facts不重复。助手本条不产事实、动作或采纳点。
明确不变、未撤回、维持猜测、排除方案、旧值或旧事件绑定作废，都是应选出的新确认/限制；不能当作重复prior省略。直接说清的用facts，需要前文才能确定具体方案的用points。更新的新值不能替代明确取消旧说法的记忆。
state.actions只给真正配置变更：set已确认新值/取消、pending撤旧且新值未定、unchanged维持、planned未来、not_applicable非配置。不凭同段别的时刻设提醒。
reminder_time仅日常单值配置；独立提醒用other逐项保存完整日期、钟点、动作、对象及次数限制，topic只写具体用途不带日期，不同用途分别保留。同字段actions至多一项，冲突不择末值。
工具可保存实际观测与明确的负向证据边界；incident_rule仅允许逐字的“本次失败不能证明…”“也不能据此判断…”等观察限制，不是用户政策。工具建议不当用户偏好/规则，不以工具观测确认业务根因；这类边界不得替换用户政策。
state.retractions逐项给被明确撤回的旧hypothesis目标和当前逐字quote，保留另一事件/另一猜测；未撤回/不是撤回/不要撤回不做动作。撤回旧说法与新确认值可同时保存。目标不存在不编造。
完整处理本批才complete=true，预算不足可false；continuation_summary只概括本批续聊状态。没有值得跨会话保存的内容也可全部为空。'''


def segments(source):
    matches=list(re.finditer(r'[^。！？!?；;\n]+[。！？!?；;\n]*|[。！？!?；;\n]+',source['text']))
    return [dict(id='s'+str(i+1),text=m.group(),start=m.start(),stop=m.end()) for i,m in enumerate(matches)]


def source_packet(source):
    return dict(id=source['id'],seq=source['seq'],role=source['role'],segments=[dict(id=s['id'],text=s['text']) for s in segments(source)])


def schema_for(ids):
    string=lambda **extra:dict(type='string',**extra)
    refs=dict(type='array',maxItems=4,uniqueItems=True,items=string())
    meta=dict(attribute=string(minLength=1,maxLength=80),lifetime=string(enum=['session','project','global']),replaces=refs)
    fact=dict(field=string(enum=FIELDS),topic=string(maxLength=80),value_text=string(minLength=1,maxLength=800),
              evidence=dict(type='array',minItems=1,maxItems=6,uniqueItems=True,items=string()),kind=string(enum=['fact','example']),
              epistemic=string(enum=['stated','hypothesis','planned','unknown']),**meta)
    point=copy.deepcopy(LINK_SCHEMA['properties']['points']['items'])
    point['properties'].update(meta);point['required']+=list(meta)
    action=dict(field=string(enum=sorted(VALUE_FIELDS)),action=string(enum=['set','pending','unchanged','planned','not_applicable']),quote=string(minLength=1))
    retract=dict(target=string(minLength=1),quote=string(minLength=1))
    obj=lambda p:dict(type='object',additionalProperties=False,properties=p,required=list(p))
    props=dict(source_id=string(enum=ids),facts=dict(type='array',maxItems=16,items=obj(fact)),
               points=dict(type='array',maxItems=4,items=point),
               state=obj(dict(actions=dict(type='array',maxItems=4,items=obj(action)),retractions=dict(type='array',maxItems=8,items=obj(retract)))))
    return obj(dict(complete=dict(type='boolean'),continuation_summary=string(maxLength=2400),
                    items=dict(type='array',minItems=len(ids),maxItems=len(ids),items=obj(props))))


def expand_fact(raw,source):
    expected={'field','topic','value_text','evidence','kind','epistemic','attribute','lifetime','replaces'}
    if not isinstance(raw,dict) or set(raw)!=expected:raise ValueError('atomic_fact_shape')
    meta=metadata(raw)
    evidence=raw['evidence'];catalog={s['id']:s for s in segments(source)}
    if not isinstance(evidence,list) or not 1<=len(evidence)<=6 or len(set(evidence))!=len(evidence) or any(x not in catalog for x in evidence):raise ValueError('atomic_evidence_ids')
    refs=[catalog[x] for x in evidence]
    for a,b in zip(refs,refs[1:]):
        if a['stop']!=b['start']:raise ValueError('atomic_evidence_must_be_contiguous')
    quote=source['text'][refs[0]['start']:refs[-1]['stop']]
    fact={k:raw[k] for k in FACT_KEYS if k!='quote'};fact['quote']=quote
    validate_fact(source['text'],fact)
    if source['role']=='tool':
        if fact['field'].startswith('incident_') and not tool_evidence_boundary(fact,meta):raise ValueError('tool_cannot_assert_business_cause')
        if fact['field']=='preference':raise ValueError('tool_cannot_set_user_policy')
    if fact['field']=='incident_cause' and fact['epistemic']=='stated':
        matching=[c for c in re.split('[，,；;。\n]',quote) if fact['value_text'] in c]
        if any(re.search('怀疑|猜测|推测|可能是',c) and not re.search('不是猜测|并非猜测|不再怀疑|撤回|收回',c) for c in matching):raise ValueError('certainty_conflicts_with_quote')
    if fact['field']=='reminder_time' and re.search(r'(?:不是|并非|不属于|别当成|不能当成).{0,6}(?:提醒|通知|闹钟)',quote):raise ValueError('non_reminder_time_role')
    if fact['field'] in VALUE_FIELDS:fact['topic']='';meta['attribute']=fact['field']
    return fact,meta


def tool_evidence_boundary(fact,meta):
    """A narrow negative observation exception, never a policy/cause assertion."""
    if (fact['field']!='incident_rule' or fact['kind']!='fact' or fact['epistemic']!='stated'
            or meta['lifetime']!='project' or meta['replace_refs']):return False
    value=fact['value_text'].strip().rstrip('。；;')
    clauses=[c.strip() for c in re.split(r'[，,；;。！？!?\n]',fact['quote'])]
    # Require the WHOLE negative clause, so selecting just its positive object
    # (e.g. "附件被删除") cannot invert the evidence boundary.
    prefix=r'(?:本次|这次|此次)?(?:失败|报错|日志|工具输出|运行结果|测试结果|响应|返回结果|观测|现有证据|该结果)?'
    negative=prefix+r'(?:也)?(?:不能|无法|不足以)(?:据此)?(?:证明|判断|确认|推断|认定).+'
    matched=value in clauses and re.fullmatch(negative,value)
    if not matched:
        # Preserve an explicitly scoped observation plus its negative inference
        # boundary as a whole, e.g. "只描述这次请求，不足以证明...".
        parts=re.split('[，,]',value)
        matched=(value==fact['quote'].strip().rstrip('。；;') and len(parts)==2
                 and re.fullmatch(r'[^。；;，,！？!?\n]{1,40}只描述(?:本次|这次|此次)(?:请求|运行|测试|观测)',parts[0])
                 and re.fullmatch(negative,parts[1]))
    if not matched:return False
    return not re.search(r'但是|但已|所以|因此|建议|应当|必须|今后|以后|下次|每次|总是',value)


def metadata(raw):
    if not isinstance(raw.get('attribute'),str) or not raw['attribute'].strip() or len(raw['attribute'].strip())>80:raise ValueError('atomic_attribute')
    if raw.get('lifetime') not in ['session','project','global']:raise ValueError('atomic_lifetime')
    refs=raw.get('replaces')
    if not isinstance(refs,list) or len(refs)>4 or any(not isinstance(x,str) or not x for x in refs) or len(set(refs))!=len(refs):raise ValueError('atomic_replace_refs')
    return dict(attribute=raw['attribute'].strip(),lifetime=raw['lifetime'],replace_refs=refs)


def batch_items(value,sources):
    """Global integrity/size gates run before any per-source work is accepted."""
    if not isinstance(value,dict) or set(value)!={'complete','continuation_summary','items'} or value['complete'] is not True:raise ValueError('incomplete_atomic_batch')
    if not isinstance(value['continuation_summary'],str) or len(value['continuation_summary'])>2400:raise ValueError('atomic_summary')
    items=value['items'];catalog={s['id']:s for s in sources}
    if not isinstance(items,list) or len(items)!=len(sources):raise ValueError('atomic_source_coverage')
    by_id={}
    for item in items:
        if not isinstance(item,dict):raise ValueError('atomic_source_id')
        sid=item.get('source_id')
        if not isinstance(sid,str) or sid not in catalog or sid in by_id:raise ValueError('atomic_source_id')
        for key,cap in [('facts',16),('points',4)]:
            if isinstance(item.get(key),list) and len(item[key])>cap:raise ValueError('atomic_item_budget')
        state=item.get('state')
        if isinstance(state,dict):
            for key,cap in [('actions',4),('retractions',8)]:
                if isinstance(state.get(key),list) and len(state[key])>cap:raise ValueError('atomic_item_budget')
        by_id[sid]=item
    return by_id


def decode_item(item,source,sources,context):
        if set(item)!={'source_id','facts','points','state'}:raise ValueError('atomic_item_shape')
        sid=source['id'];state=item['state']
        if not isinstance(item['facts'],list) or len(item['facts'])>16 or not isinstance(item['points'],list) or len(item['points'])>4:raise ValueError('atomic_item_budget')
        if not isinstance(state,dict) or set(state)!={'actions','retractions'} or not isinstance(state['actions'],list) or len(state['actions'])>4 or not isinstance(state['retractions'],list) or len(state['retractions'])>8:raise ValueError('atomic_state_shape')
        if source['role']=='assistant' and (item['facts'] or item['points'] or any(state.values())):raise ValueError('assistant_is_not_authority')
        result=dict(facts=[],claim_specs=[],linked_points=[],linked_specs=[],session_points=[],semantic_actions={},semantic_review=dict(actions=[]),retract_claims=[],diagnostics=[])
        for index,raw in enumerate(item['facts']):
            fact,meta=expand_fact(raw,source);meta['ordinal']=index
            if meta['lifetime']=='session':
                result['session_points'].append(dict(source_id=sid,record_type='fact',fact=fact,**meta));continue
            result['facts'].append(fact);result['claim_specs'].append(meta)
        for index,raw in enumerate(item['points']):
            if not isinstance(raw,dict) or set(raw)!={'statement','epistemic','evidence','attribute','lifetime','replaces'}:raise ValueError('atomic_point_shape')
            point={k:raw[k] for k in ['statement','epistemic','evidence']};validate_point(point,source,context+sources)
            if source['role']!='user':raise ValueError('linked_confirmation_role')
            meta=metadata(raw);meta['ordinal']=index
            if meta['lifetime']=='session':result['session_points'].append(dict(source_id=sid,record_type='linked',point=point,**meta));continue
            result['linked_points'].append(point);result['linked_specs'].append(meta)
        for action in state['actions']:
            if not isinstance(action,dict) or set(action)!={'field','action','quote'} or action['field'] not in VALUE_FIELDS or action['action'] not in ['set','pending','unchanged','planned','not_applicable'] or not isinstance(action['quote'],str) or not action['quote'] or action['quote'] not in source['text']:raise ValueError('atomic_action')
            if action['field'] in result['semantic_actions']:raise ValueError('duplicate_atomic_action')
            result['semantic_actions'][action['field']]=action['action'];result['semantic_review']['actions'].append(action)
        for change in state['retractions']:
            if not isinstance(change,dict) or set(change)!={'target','quote'} or not isinstance(change['target'],str) or not change['target'] or not isinstance(change['quote'],str) or not change['quote'] or change['quote'] not in source['text']:raise ValueError('atomic_retraction')
            result['retract_claims'].append(dict(ref=change['target'],quote=change['quote']))
        if any(result['semantic_actions'].get(f['field'])=='not_applicable' and f['kind']=='fact' for f in result['facts']):
            raise ValueError('atomic_field_action_contradiction')
        return result


def decode(value,sources,context):
    """Strict helper retained for callers that need an all-valid proposal."""
    items=batch_items(value,sources)
    return {s['id']:decode_item(items[s['id']],s,sources,context) for s in sources}


def decode_isolated(value,sources,context):
    items=batch_items(value,sources);results={};failed={}
    for source in sources:
        sid=source['id']
        try:results[sid]=decode_item(items[sid],source,sources,context)
        except (ValueError,TypeError,KeyError) as exc:failed[sid]=dict(error=type(exc).__name__,reason=str(exc)[:300])
    return results,failed


def estimate_output(sources,count):
    """Conservative preflight estimate; actual commit still checks the cap."""
    authored=[s for s in sources if s['role']!='assistant']
    text_tokens=sum(count(s['text']) for s in authored)
    return int(180+len(sources)*28+len(authored)*96+2.2*text_tokens)


def target_candidates(catalog,sources,limit=8,*,required_by_source=None):
    from .reminders import is_event_reminder,reminder_change_clauses,reminder_label,compact
    # A question/tool observation elsewhere in a batch must not veto an actual
    # user change. Mirror the enqueue guard's named-purpose/ambiguity boundary.
    reminder_ids=set();required_by_source=required_by_source or {}
    for source in sources:
        if source.get('role')!='user':continue
        def precedes(row):
            return (all(key not in row or key not in source or row[key]==source[key] for key in ['project','entity'])
                    and (not isinstance(row.get('seq'),int) or not isinstance(source.get('seq'),int) or row['seq']<source['seq'])
                    and (row.get('valid_to') is None or not isinstance(source.get('seq'),int) or row['valid_to']>=source['seq']))
        reminders=[r for r in catalog if precedes(r) and is_event_reminder(r,r.get('attribute',''))]
        possible=[r for r in reminders if reminder_change_clauses(source['text'],r)]
        literal=[r for r in possible if reminder_label(r) in compact(source['text'])]
        if literal:possible=literal
        elif len({reminder_label(r) for r in possible})>1:possible=[]
        reminder_ids.update(r['id'] for r in possible)
        # These are the store's already grounded, source-specific obligations,
        # not every pending target in the scope. Do not re-guess their label.
        reminder_ids.update(r['id'] for r in reminders if r['id'] in required_by_source.get(source['id'],()))
    text='\n'.join(s['text'] for s in sources if s['role']!='assistant')
    withdrawing=bool(re.search('撤回|撤掉|收回|作废|不再采信|推翻',text))
    changing=bool(re.search('改为|改成|改到|改期|挪到|移到|延期|推迟|提前|更正|纠正|调整|不再|取消|换用|撤回|撤掉|收回',text))
    protected=[];ranked=[]
    def words(value):return {value[i:i+2] for i in range(max(0,len(value)-1)) if value[i:i+2].strip()}
    query=words(text)
    for row in catalog:
        name=row.get('topic','');attr=row.get('attribute','');value=row.get('value','')
        exact=(bool(name) and name in text) or (bool(attr) and attr in text) or (len(value)>=4 and value in text)
        reminder=is_event_reminder(row,row.get('attribute',''))
        required=row['id'] in reminder_ids or (not reminder and ((withdrawing and row['epistemic']=='hypothesis' and (exact or not any(c.get('topic') and c['topic'] in text for c in catalog if c['epistemic']=='hypothesis'))) or (changing and exact)))
        score=(5 if exact else 0)+len(query&words(value+' '+name+' '+attr))/max(1,len(words(value+' '+name+' '+attr)))
        (protected if required else ranked).append((score,row))
    protected=sorted(protected,key=lambda x:(-x[0],-x[1]['seq'],x[1]['id']))
    ranked=sorted(ranked,key=lambda x:(-x[0],-x[1]['seq'],x[1]['id']))
    # All required targets stay, even if this means reducing the source batch.
    return [r for _,r in protected]+[r for _,r in ranked[:max(0,limit-len(protected))]],len(protected)
