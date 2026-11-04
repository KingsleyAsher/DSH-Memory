"""Source-bounded extraction repair. No labels, query text or new weights."""
import copy,re
from .contract import PROMPT,SCHEMA,validate_fact,normalize,TOPICS,EXAMPLE
from .extraction_base import extract as previous_extract,make_fact,clauses,sentences,local_kind,rejected_literal,state_fallbacks

EMAIL=r'(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.\-])'
EVENT_WORDS=TOPICS+['导入','下载','解析','支付','推送','渲染','连接','授权','编译']
EXTRA='''补充要求：邮箱与电话是不同类型，邮箱用other、topic=email，逐字保存完整地址；不要将邮箱塞进contact_phone。
故障topic尽量用原文中能区分事件的完整短名称，如图片上传、票据上传；同一事件的原因/处理/防错使用同一个名称，不把两种上传故障合在一起。未查明状态和具体怀疑原因分别提取，保留各自限定词。
偏好中的触发条件必须完整保存。示例配置不是偏好，普通工作事实不必牵强归为偏好。'''
EXTRA+='\n部署状态的topic使用原文里具体功能名称，例如告警、自动盘点，功能不同不能合并。尚未执行与计划、已经验证通过分开保存；其余配置/偏好topic仍填空。执行失败只记录观测，不凭错误日志猜根因。'
EXTRA+='\n状态按当前具体能力的范围保存：某一区域已部署、其他区域未部署必须保留。所有能力分别提取，不要只保存最后一个。执行命令的错误码和未产出结果使用other、topic=execution，不能当作业务故障根因。目录仍是此前那项等不变指代不产生新配置或未知状态。不要将“别把甲当成乙”的提醒单独提为原因事实。'
EXTRA+='\n逐个摘出有后续作用的身份、项目要求、权限/隐私约束、明确决定、错误及验证经过，不局限于软件故障。主题标签规范失败不等于内容无效。value_text须明确表达记忆点，quote只提供必要上下文，不用整段引文冒充已提炼。相同主张只提一次，条件和结论保持在一起；已执行的步骤与未来计划分别提，不能让引语中的“可能”改变外层已发生行为的状态。无后续用途的景色和临时身体感受通常不记。'

def email_anchors(text):
    out=[]
    for sentence in sentences(text):
        if sentence.endswith(('？','?')) and not re.search(r'记为|设为|改为|更正|请保存',sentence):continue
        if not re.search(r'邮箱|邮件|email|e-mail',sentence,re.I):continue
        for clause in clauses(sentence):
            for match in re.finditer(EMAIL,clause):
                value=match.group()
                if not rejected_literal(clause,value):out.append(make_fact('other',value,clause,topic='email',kind=local_kind(text,value)))
    return out

def repair_facts(text,base_facts,outputs):
    facts=[copy.deepcopy(f) for f in base_facts if not f['field'].startswith('incident_')]
    for f in facts:
        if f['field']=='other' and re.fullmatch(EMAIL,f['value_text']):f['topic']='email'
    events=[];errors=[]
    for out in outputs:
        proposal=out.get('value')
        if not isinstance(proposal,dict) or not isinstance(proposal.get('facts'),list):continue
        for raw in proposal['facts']:
            if isinstance(raw,dict) and raw.get('field')=='deployment_state' and raw.get('topic') and raw['topic'] in text:
                candidate=copy.deepcopy(raw)
                try:
                    validate_fact(text,candidate)
                    # Preserve the whole capability-specific sentence, not an
                    # entire paragraph mixing unrelated deployment statuses.
                    context=next((s for s in sentences(text) if candidate['quote'] in s),candidate['quote'])
                    candidate['quote']=context
                    if re.search(r'尚未|还没|没有|未部署|未上线',context):candidate['epistemic']='stated'
                    facts=[f for f in facts if not (f['field']=='deployment_state' and (f['quote'] in context or not f['topic']))]
                    facts.append(candidate)
                except (ValueError,TypeError,KeyError):pass
            if not isinstance(raw,dict) or not str(raw.get('field','')).startswith('incident_'):continue
            f=copy.deepcopy(raw)
            try:
                if isinstance(f.get('quote'),str) and f['quote'] in text and isinstance(f.get('value_text'),str) and f['value_text'] not in f['quote']:f['value_text']=f['quote']
                validate_fact(text,f)
                context=next((s for s in sentences(text) if f['quote'] in s),f['quote'])
                f['kind']=local_kind(text,f['value_text'],f['quote'])
                # Preserve literal specific event names; only derive a generic
                # name when the source itself contains one unambiguous event.
                if not f['topic'] or f['topic'] not in text:
                    nearby=[t for t in EVENT_WORDS if t in context]
                    whole=[t for t in EVENT_WORDS if t in text]
                    f['topic']=nearby[0] if len(nearby)==1 else whole[0] if len(whole)==1 else ''
                if not f['topic']:
                    errors.append(dict(reason='event_scope_unresolved',fact=raw));continue
                if f['field']=='incident_cause':
                    f['quote']=context
                    if re.search(r'未.*(?:查|确认|定位)|没.*(?:查|确认|定位|结论)|未知|不确定',f['value_text']):f['epistemic']='unknown'
                    elif re.search(r'怀疑|猜测|可能|推测|待验证',context):f['epistemic']='hypothesis'
                events.append(f)
            except (ValueError,KeyError,TypeError) as exc:errors.append(dict(reason=str(exc),fact=raw))
    # Retain source-bound unknown/hypothesis fallbacks when the model omitted
    # them. Status belongs in the dedup key; equal quotes need not equal states.
    for f in base_facts+state_fallbacks(text):
        if not f['field'].startswith('incident_'):continue
        if not any(e['field']==f['field'] and e['epistemic']==f['epistemic'] and f['quote'] in e['quote'] for e in events):events.append(copy.deepcopy(f))
    facts+=events+email_anchors(text)
    unique={}
    for f in facts:
        validate_fact(text,f)
        unique.setdefault((f['field'],f['kind'],f['topic'],f['epistemic'],normalize(f['field'],f['value_text'])),f)
    return list(unique.values()),errors

def extract(source,prior,call,*,recent=None,review_candidates=False):
    outputs=[]
    def wrapped(system,payload,schema,*,max_tokens):
        out=call(system+'\n'+EXTRA,payload,schema,max_tokens=max_tokens);outputs.append(out);return out
    result=previous_extract(source,prior,wrapped)
    if source['role'] not in ['user','tool']:return result
    result['facts'],extra=repair_facts(source['text'],result['facts'],outputs)
    result['facts']=complete_frames(source,prior,result['facts'])
    from .grounding import restore
    deferred=[]
    result['facts'],grounding_errors=restore(source,result['facts'],outputs,deferred)
    result['deferred_points']=deferred
    result['diagnostics']+=extra
    result['diagnostics']+=grounding_errors
    from .contextual import resolve_accepted
    result['linked_points'],context_calls,context_errors=resolve_accepted(source,recent or [],call,existing_facts=result['facts'],prior=prior)
    result['calls']+=context_calls;result['diagnostics']+=context_errors
    if review_candidates:
        from .admission import select
        result=select(source,prior,result,recent or [],call)
    return result

def complete_frames(source,prior,facts):
    """Source-visible coverage, event dedup and observation typing."""
    text=source['text'];out=[]
    # A failed tool run is an observation; its literal error name is not a
    # proven cause of a different business incident mentioned in commentary.
    if source['role']=='tool' and re.search(r'退出码|错误[A-Z_]|返回[A-Z_]|输出[A-Z_]',text):
        observed=re.split(r'这里|日志(?:只是|没有|未)|执行日志|不要|不能据此|这(?:条|个)(?:观测|输出)',text)[0].strip()
        facts=[f for f in facts if not f['field'].startswith('incident_')]
        if observed:facts.append(make_fact('other',observed,observed,topic='execution'))
    # Recover source-local capability sentences using literal names proposed
    # by the model or previously declared, never a question/gold dictionary.
    labels={f['topic'] for f in facts+prior if f['field']=='deployment_state' and f.get('topic') and f['topic'] in text}
    candidates=[];context=''
    for sentence in sentences(text):
        if not re.search(r'部署|上线|投用|投入使用|验收',sentence):continue
        named=[n for n in labels if n in sentence];named=[n for n in named if not any(n!=x and n in x for x in named)]
        if context and len(named)==1 and re.search(r'(?:灯区|网点|车间|站点|节点|终端|号炉|号库|区|台|站|库|间)$',named[0]) and not re.search(r'告警|报警|监控|排班|编排|巡测|归色|补单',named[0]):
            area=named[0];facts=[f for f in facts if not (f['field']=='deployment_state' and f['topic']==area and f['quote'] in sentence)]
            named=[context]
        primary=re.match(r'(?:另外|而|至于|目前|现在|更新：|更新:|更正：)?\s*([\u4e00-\u9fffA-Za-z]{2,12}?)(?:已经|已|尚未|还没|仍未|计划|只在|仅在)',sentence)
        if primary and primary.group(1) in named:
            # A location named later in this capability's status sentence is
            # scope, not a newly deployed feature of its own.
            subordinate=[n for n in named if n!=primary.group(1) and sentence.find(n)>sentence.find('，')>=0 and re.search(r'区|点|车间|楼|站|库|炉|店|节点|终端',n)]
            for n in subordinate:
                facts=[f for f in facts if not (f['field']=='deployment_state' and f['topic']==n and f['quote'] in sentence)]
            named=[n for n in named if n not in subordinate]
        if not named:
            m=re.match(r'(?:另外|而|至于|目前|现在|更新：|更新:|更正：)?\s*([\u4e00-\u9fffA-Za-z]{2,12}?)(?:已经|已|尚未|还没|仍未|计划|只在|仅在)',sentence)
            if m:named=[m.group(1)];labels.update(named)
        if len(named)==1:context=named[0]
        elif len(named)>1:continue
        if not named and not context:continue
        name=named[0] if named else context
        # Do not label a different feature based on a previous sentence.
        if not named and not re.match(r'(?:其余|其他|二号|第二|西区|合作|尚未|仍未|只有|仅|[^，。；]{1,12}(?:尚未|仍未|未部署))',sentence):continue
        state='planned' if re.search(r'计划|打算|准备',sentence) and not re.search(r'已部署|已上线',sentence) else 'stated'
        candidates.append(make_fact('deployment_state',sentence,sentence,topic=name,kind=local_kind(text,sentence),epistemic=state))
    if candidates:
        names={f['topic'] for f in candidates}
        facts=[f for f in facts if not (f['field']=='deployment_state' and (not f['topic'] or f['topic'] in names))]+candidates
    from .relations import deployment_frames
    facts=deployment_frames(text,facts)
    specific={f['topic'] for f in facts if f['field'].startswith('incident_') and len(f['topic'])>2}
    for f in facts:
        f=copy.deepcopy(f)
        if f['field'].startswith('incident_'):
            choices=[n for n in specific if f['topic'] in n and n in f['quote']]
            if len(f['topic'])<=2:
                if len(choices)==1:f['topic']=choices[0]
                elif len(choices)>1:continue
                else:
                    pos=text.find(f['quote']);previous=[(text.rfind(n,0,pos),n) for n in specific if text.rfind(n,0,pos)>=0 and pos-text.rfind(n,0,pos)<120]
                    if previous:f['topic']=max(previous)[1]
            if re.match(r'(?:别|不要|不能|不应)(?:把|拿|因为)',f['value_text']):continue
            if f['epistemic']=='unknown':
                value=re.split(r'[；;](?:别|不要|不能|不应)',f['value_text'])[0]
                if value and value in f['quote']:f['value_text']=value
        validate_fact(text,f)
        key=(f['field'],f['topic'],f['kind'],f['epistemic'])
        duplicates=[g for g in out if (g['field'],g['topic'],g['kind'],g['epistemic'])==key]
        if any(f['value_text'] in g['value_text'] or g['value_text'] in f['value_text'] for g in duplicates):
            # Prefer a concise explicit unknown over instruction-heavy fallback.
            if f['epistemic']=='unknown' and duplicates and len(f['value_text'])<len(duplicates[0]['value_text']):out.remove(duplicates[0])
            else:continue
        out.append(f)
    return out
