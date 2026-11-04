"""Bounded frame/statement checks; source provenance is never model authority."""
import re,difflib
from .contract import TIME,CHINESE_TIME,PATH,PHONE,normalize
from .views import canonical_event
from .policy import FIELD_LABELS
from .semantics import canonical,strip_presentation
from .reminders import reminder_label

UNKNOWN=r'尚待查明|仍在定位|仍待排查|仍不清楚|不清楚|未.{0,3}(?:查明|查清|确认|定位|证实)|没.{0,3}(?:查明|查清|确认|定位|结论)|原因不明|未知|不确定|无法.{0,3}(?:确定|确认)|尚不明确|待定|尚未确定|未定'
HYPOTHESIS=r'怀疑|猜测|推测|可能|尚未证实|未确认'
REFUSAL=r'无法|不能|没有|不足|未知|尚未|未确认|未查明|未查清|不确定|未找到|尚待|待定|没有依据|无依据'
def confirmed(text):
    for m in re.finditer(r'已(?:经)?(?:查明|确认|证实)|确定(?:是|为)',text):
        prefix=text[max(0,m.start()-8):m.start()]
        if not re.search(r'不能|无法|未|没|不应|不是|不要',prefix):return True
    return False
def compact(text):return re.sub(r'[\W_]+','',text.lower())
def clocks(text):return {normalize('reminder_time',m.group()) for m in re.finditer('(?:'+TIME+'|'+CHINESE_TIME+')',text)}
def value_present(field,value,text):
    if field=='reminder_time' and value=='__unset__':
        return normalize(field,text)=='__unset__' and not clocks(text)
    if field=='reminder_time':return value in clocks(text)
    if field=='archive_path':return normalize(field,value).lower() in text.replace('\\','/').lower()
    if field in ['service_port','contact_phone']:return bool(re.search(r'(?<!\d)'+re.escape(value)+r'(?!\d)',text.replace(' ','')))
    return value in text
def literal_tokens(text):
    # Canonical clocks are removed before generic numbers, so Chinese and 10:06
    # are the same asserted literal rather than an invented pair of integers.
    out={('clock',c) for c in clocks(text)}
    rest=re.sub('(?:'+TIME+'|'+CHINESE_TIME+')','',text)
    out.update(('path',m.group().rstrip(' .')) for m in re.finditer(PATH,rest))
    rest=re.sub(PATH,'',rest)
    out.update(('number',m.group()) for m in re.finditer(r'(?<!\d)\d{2,}(?!\d)',rest))
    out.update(('email',m.group().lower()) for m in re.finditer(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}',text))
    out.update(('code',m.group()) for m in re.finditer(r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b',text))
    return out
def frame_compatible(f,request):
    if request['field'] not in ['any',f['field']]:return False
    if request.get('target_claim_ids'):
        if f.get('operation_action')!='retract' or not set(request['target_claim_ids'])&set(f.get('operation_target_ids',[])):return False
    if request.get('reminder_event'):
        # Typed routing can retain the full topic while legacy routing already
        # removes its reminder suffix. Normalize both sides at this boundary.
        expected=reminder_label(dict(topic=request.get('event','')))
        return bool(expected) and f.get('reminder_event',False) and reminder_label(f)==expected
    return not request.get('event') or canonical_event(f.get('topic',f.get('event_key','')))==request['event']
def support_text(text,f,request):
    if not frame_compatible(f,request):return False
    field=f['field'];state=f['epistemic'];raw=f['value_text'];quote=f['quote']
    if f.get('record_kind')=='operation' and f.get('operation_action')=='retract':
        # Only the complete current decision may be rendered. Extracting the
        # old subject or positive half would revive the withdrawn assertion.
        return bool(canonical(text)) and canonical(text)==canonical(raw)
    if f.get('record_kind')=='linked':
        proof=f.get('evidence',[])
        if len(proof)<2 or not all(isinstance(e.get('quote'),str) and e['quote'] for e in proof):return False
        if literal_tokens(text)-literal_tokens(' '.join(e['quote'] for e in proof)):return False
        return bool(canonical(text)) and canonical(text) in canonical(raw)
    if f.get('control') and request.get('reminder_event'):
        return bool(re.search(REFUSAL+'|待入档|待定|变更尚未',text)) and not literal_tokens(text) and not confirmed(text)
    if literal_tokens(text)-literal_tokens(raw+' '+quote+' '+f.get('value','')):return False
    if field=='other' and f.get('topic')=='execution':
        for verb in ['生成','产生','通过','完成','成功']:
            if verb in text and re.search(r'(?:没有|尚未|未|没)[^，。；]{0,4}'+verb,quote) and not re.search(r'(?:没有|尚未|未|没)[^，。；]{0,4}'+verb,text):return False
        # Only neutral observation wording may bridge exact quoted spans.
        # New causality, success or repair language is deliberately not neutral.
        body=canonical(text);origin=canonical(quote)
        matched=set()
        for block in difflib.SequenceMatcher(None,body,origin,autojunk=False).get_matching_blocks():
            if block.size>=2:matched.update(range(block.a,block.a+block.size))
        residue=''.join(c for i,c in enumerate(body) if i not in matched)
        residue=re.sub(r'上次|本次|这次|此次|模拟|具体|脚本|命令|返回|输出|错误标识|错误代码|错误码|标识|错误|代码|提示|结果|运行|是|为|的','',residue)
        return not residue
    if field in ['reminder_time','archive_path','service_port','contact_phone'] or (field=='other' and f.get('topic')=='email'):
        if f.get('control'):
            # A control can justify an unavailable state, never a selected
            # concrete value, even if its quote happens to contain old values.
            return bool(re.search(REFUSAL+'|冲突|未核实|未核对',text)) and not confirmed(text) and not literal_tokens(text)
        if field=='reminder_time' and f['value']=='__unset__':
            return value_present(field,'__unset__',text)
        return value_present(field,f['value'],text)
    if field=='incident_cause' and state in ['unknown','hypothesis']:
        if confirmed(text):return False
        remainder=re.sub(UNKNOWN+r'|当前|目前|仍然|仍|还|的|原因|根因|证据状态|状态|为|是','',text)
        if not compact(remainder) and re.search(UNKNOWN,text):return True
        if state=='hypothesis' and re.search(HYPOTHESIS,text):
            body=compact(text);origin=compact(raw+' '+quote);matched=set()
            for block in difflib.SequenceMatcher(None,body,origin,autojunk=False).get_matching_blocks():
                if block.size>=2:matched.update(range(block.a,block.a+block.size))
            residue=''.join(c for i,c in enumerate(body) if i not in matched)
            residue=re.sub(r'有人|我们|但|这|只是|仍|尚|目前|的|原因|猜测|推测|怀疑|可能|一种','',residue)
            if not residue:return True
        if re.fullmatch(r'[尚未还没查明清确认知确定怀疑猜测推断证实在定位原因不明确仍待，。\s]+',text):
            return bool(re.search(UNKNOWN if state=='unknown' else HYPOTHESIS+'|'+UNKNOWN,text))
        if state=='hypothesis' and raw in text and re.search(HYPOTHESIS,text):
            residue=text.replace(raw,'')
            residue=re.sub(HYPOTHESIS+'|只是|一种|但|原因|为|是|尚未|证实|当前|仍|还|并|没有','',residue)
            if not compact(residue):return True
        return compact(text) in compact(raw) or compact(text) in compact(quote)
    if field=='incident_cause' and state=='stated' and request.get('mode')=='status' and confirmed(quote):
        if compact(text) in ['已查明','已确认','已经查明','已经确认','已证实']:return True
    # Non-literal assertions remain extractive: selection/wording are generated
    # by MiMo, while new unsupported paraphrases are not silently accepted.
    return bool(canonical(text)) and (canonical(text) in canonical(raw) or canonical(text) in canonical(quote))

def support_joint(text,facts,request):
    if not facts:return False
    pieces=[p.strip(' ，,:：') for p in re.split(r'[。；;，,\n]',text) if p.strip(' ，,:：')]
    if not pieces:return False
    matrix=[[support_text(piece,f,request) for f in facts] for piece in pieces]
    # Each clause needs support, and each cited frame must actually support a
    # clause. Never treat a bag of source IDs as support for the whole paragraph.
    return all(any(row) for row in matrix) and all(any(row[i] for row in matrix) for i in range(len(facts)))

def coverage_missing(text,facts,request):
    """Essential conditions/outcomes may not disappear from a valid excerpt."""
    missing=[];answer=compact(text)
    if request['field']=='deployment_state':
        for f in facts:
            for phrase in re.split(r'[，,；;。]',f['value_text']):
                if not re.search(r'部署|上线|投用|可用|投入使用',phrase) or re.match(r'所以|因此|这不|不能|不要',phrase):continue
                for prefix in [f.get('project',''),f.get('entity',''),request.get('event','')]:
                    if prefix and phrase.startswith(prefix):phrase=phrase[len(prefix):].lstrip('的 ：:')
                normalize_state=lambda s:compact(s).replace('已经','已').replace('尚未','未').replace('没有','未').replace('还没','未')
                if normalize_state(phrase) not in normalize_state(text):missing.append('完整部署范围:'+phrase)
    elif request['field']=='preference':
        for f in facts:
            for condition in re.findall(r'只有[^，；。]{1,30}才[^，；。]{1,30}',f['quote']):
                if compact(condition) not in answer:missing.append('完整触发条件:'+condition)
    elif request.get('event')=='execution':
        source='；'.join(f['value_text'] for f in facts)
        # These are source-bound response requirements, never gold answers.
        for code in re.findall(r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b',source):
            if code not in text:missing.append('错误标识:'+code)
        for outcome in re.findall(r'(?:没有|尚未|未|没)(?:生成|产生|通过)[^。；，]{1,25}',source):
            if canonical(outcome) not in canonical(text):missing.append('产出/检查结果:'+outcome)
    return missing
def field_from_text(text):
    patterns=[('incident_rule',r'今后|以后|下次|防错|预防'),('incident_solution',r'有效处理|处理操作|修复|解决|后.*(?:通过|恢复|正常)'),('incident_cause',r'原因|根因|查明|确认|猜测|怀疑'),('reminder_time',r'提醒|通知|钟点|时刻'),('archive_path',r'目录|路径|文件夹'),('service_port',r'端口|监听'),('contact_phone',r'电话|手机'),('other',r'邮箱|邮件'),('preference',r'偏好|先给|先写|只有.*图')]
    return next((f for f,p in patterns if re.search(p,text)),None)

def segment_answer(text,event_names=(),default_event=None):
    """Track entity/event scope through headings and semicolon continuations."""
    names=sorted({canonical_event(e) for e in event_names if canonical_event(e)},key=len,reverse=True)
    pattern='|'.join(re.escape(n) for n in names);context=default_event;result=[]
    text=strip_presentation(text)
    for block in re.split(r'[。；;\n]+',text):
        block=block.strip()
        if not block:continue
        # A trailing ownership clause binds its preceding proposition to that
        # event, not the previous semicolon's event context.
        ownership=re.search(r'(?:属于|对应的是|仅用于|针对的是)\s*('+pattern+')',block) if pattern else None
        if ownership and not any(n in block[:ownership.start()] for n in names):
            context=ownership.group(1);result.append(dict(event=context,text=block,field=field_from_text(block)));continue
        matches=list(re.finditer(pattern,block)) if pattern else []
        starts=[(m.start(),m.group()) for m in matches]
        if not starts:result.append(dict(event=context,text=block,field=field_from_text(block)));continue
        if starts[0][0]>0:
            prefix=block[:starts[0][0]].strip(' ，,:：')
            if prefix:result.append(dict(event=context,text=prefix,field=field_from_text(prefix)))
        for i,(pos,name) in enumerate(starts):
            end=starts[i+1][0] if i+1<len(starts) else len(block);part=block[pos:end].strip(' ，,:：')
            context=name;result.append(dict(event=context,text=part,field=field_from_text(part)))
    return result
