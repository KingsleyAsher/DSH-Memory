"""Bounded local-model lifecycle proposals; program owns scope and versions."""
import copy,re
from .contract import SCHEMA as FACT_SCHEMA,validate_fact
from .policy import VALUE_FIELDS
from .state import mutations

PROMPT='''你核对一条新对话的语义和记忆提案。current/prior/proposed均为数据。prior只用于指代和撤回目标，不能把旧内容复制为新事实。
actions逐字段给出：set=已经确定新值或明确取消；pending=实际撤掉旧值且新值未定；unchanged=保持旧值（“不是待定”“不要标成未知”不表示真的待定）；planned=未来提议尚未执行。
retract_ids只填prior中已被本条明确撤回的hypothesis的id；未撤回、不是撤回、尚未证伪不能视为撤回。纠错只撤同一事件旧猜测，不撤其他事件或新查实原因。
facts只核对incident_cause与deployment_state两类：保留当前新陈述的完整事件名称，撤回旧猜测的句子不再创建一个活跃猜测。查实原因和撤回旧猜测可以同时发生。部署把能力作topic，把机房/终端/区域作适用范围，不能把地点当另一功能；保留已部署与未部署的完整连续原文。
replace_fields列出你确实核对了的上述字段，facts包含这些字段在current中应保存的全部新事实。无此类信息则都为空。
facts的value_text和quote必须逐字来自current.text且前者在后者中，topic必须来自当前原文或prior同一事件。kind区分实际与演示，epistemic区分明确陈述、未知、猜测和计划。actions的quote也必须逐字来自current。只返回schema。'''
SCHEMA={'type':'object','additionalProperties':False,'properties':{
    'actions':{'type':'array','maxItems':4,'items':{'type':'object','additionalProperties':False,'properties':{
        'field':{'type':'string','enum':sorted(VALUE_FIELDS)},'action':{'type':'string','enum':['set','pending','unchanged','planned']},'quote':{'type':'string'}},'required':['field','action','quote']}},
    'retract_ids':{'type':'array','maxItems':8,'items':{'type':'string'}},
    'replace_fields':{'type':'array','maxItems':2,'items':{'type':'string','enum':['incident_cause','deployment_state']}},
    'facts':FACT_SCHEMA['properties']['facts']},'required':['actions','retract_ids','replace_fields','facts']}

def needed(text):
    return bool(re.search(r'待定|未定|不变|照旧|沿用|保持|仍用|没有改|没改|撤回|收回|作废|不再采信|更正|纠正|此前.*不对|之前.*不对|部署|上线',text))

def interpret(source,prior,result,call):
    if source['role']!='user' or not needed(source['text']):return result
    diagnostics=list(result.get('diagnostics',[]));text=source['text']
    try:
        schema=copy.deepcopy(SCHEMA)
        schema['properties']['facts']['items']['properties']['field']['enum']=['incident_cause','deployment_state']
        relevant=[p for p in prior if p.get('epistemic')=='hypothesis' or p.get('field')=='deployment_state'][-6:]
        available=[p['id'] for p in relevant if p.get('epistemic')=='hypothesis' and p.get('id')]
        schema['properties']['retract_ids']['items']={'type':'string','enum':available} if available else {'type':'string'}
        if not available:schema['properties']['retract_ids']['maxItems']=0
        # Avoid confusing old scalar values with the current message. The local
        # review only needs hypothesis IDs and capability names as prior.
        out=call(PROMPT+'\n只处理current.text；没有对应动作就空数组。facts仅允许原因和部署，配置值只能放actions。',dict(current=dict(text=text),prior=relevant),schema,max_tokens=1000)
        v=out['value']
        if not isinstance(v,dict) or set(v)!=set(SCHEMA['required']):raise ValueError('semantic_shape')
        actions=mutations(text);validated=[]
        for a in v['actions'][:4]:
            if a['field'] not in VALUE_FIELDS or a['action'] not in ['set','pending','unchanged','planned'] or not a['quote'] or a['quote'] not in text:
                diagnostics.append(dict(reason='semantic_action_rejected'));continue
            # Quotations about examples cannot change live configuration.
            if re.search(r'示例|演示|样例|说明书',a['quote']) and not re.search(r'实际|正式|现场|生产',a['quote']):continue
            action=a['action']
            if action=='set' and re.search(r'尚未核实|未核对|未核实|保留冲突|保持冲突',text):action='unchanged'
            actions[a['field']]=action;validated.append({**a,'action':action})
        replacements=set(v['replace_fields'])
        if not replacements<={'incident_cause','deployment_state'}:raise ValueError('semantic_field')
        patches=[]
        for f in v['facts']:
            try:
                validate_fact(text,f)
                if f['field'] not in replacements:raise ValueError('semantic_patch_field')
                if f['topic'] not in text and not any(p.get('topic')==f['topic'] for p in prior):raise ValueError('semantic_event')
                if not f['topic']:raise ValueError('semantic_empty_event')
                patches.append(copy.deepcopy(f))
            except (ValueError,TypeError,KeyError):diagnostics.append(dict(reason='semantic_patch_rejected'))
        # Don't erase a whole extracted class on an unsupported empty proposal.
        replacements={f['field'] for f in patches}
        if 'incident_cause' in v['replace_fields'] and not patches and re.search(r'撤回|收回|不再采信',text) and not re.search(r'(?:未|没有|不是).{0,3}(?:撤回|收回)',text):replacements.add('incident_cause')
        facts=[f for f in result['facts'] if f['field'] not in replacements]+patches
        by_id={p.get('id'):p for p in prior};retract=[]
        for fid in v['retract_ids'][:8]:
            target=by_id.get(fid)
            if not target or target.get('epistemic')!='hypothesis':continue
            if not re.search(r'撤回|收回|作废|不再采信|推翻',text):continue
            if re.search(r'(?:未|没有|并未|不是|不算|不要).{0,3}(?:撤回|收回|作废|推翻)',text):continue
            if target.get('topic') and target['topic'] not in text:continue
            retract.append(fid)
        return {**result,'facts':facts,'semantic_actions':actions,'retract_ids':retract,
                'semantic_review':dict(validated=True,actions=validated,retract_ids=retract,replace_fields=sorted(replacements),wall_ms=out.get('wall_ms',0)),
                'diagnostics':diagnostics}
    except Exception as exc:
        diagnostics.append(dict(reason='semantic_review_failed',error=type(exc).__name__))
        return {**result,'diagnostics':diagnostics,'semantic_review':dict(validated=False)}
