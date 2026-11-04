"""Source-bound 0/1..4 representations; quantity is an auditable estimate."""
import hashlib,json,re
def digest(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def canonical_event(label):return re.sub(r'(?:失败|故障|异常|中断)$','',re.sub(r'[\W_的]+','',label))
def base_text(unit):
    facts='；'.join(f"{f['field']}={f['value_text']}（{f['epistemic']}）" for f in unit['facts'])
    return f"项目：{unit['project']}；对象：{unit['entity']}；事件：{unit.get('event_key','')}；类型：{unit['kind']}。{facts}"
def propose(unit,cap=4,semantic=True):
    if not semantic:return []
    base=base_text(unit);out=[dict(purpose='base',text=base,fact_ids=[f['id'] for f in unit['facts']],reason='canonical complete representation')]
    # Single frames stay one vector. Composite events may expose independent
    # grounded facets; identical quotes do not get extra vectors just for labels.
    if len(unit['facts'])<2:return out
    seen=set();purposes=set()
    for fact in sorted(unit['facts'],key=lambda f:({'incident_cause':0,'incident_solution':1,'incident_rule':2}.get(f['field'],3),f['id'])):
        if not fact['field'].startswith('incident_'):continue
        purpose='state' if fact['epistemic'] in ['unknown','hypothesis','planned'] else fact['field']
        quote=fact['quote'];normalized=re.sub(r'\s+|[，。；,;]','',quote)
        if normalized in seen or purpose in purposes:continue
        seen.add(normalized);purposes.add(purpose)
        text=f"项目：{unit['project']}；对象：{unit['entity']}；事件：{unit.get('event_key','')}；状态：{fact['epistemic']}；用途：{purpose}。{quote}"
        out.append(dict(purpose=purpose,text=text,fact_ids=[fact['id']],reason='distinct source-bound retrieval purpose'))
        if len(out)>=cap:break
    return out[:cap]
def fingerprint(unit):
    return digest(json.dumps(dict(source_id=unit['source_id'],facts=[{k:f[k] for k in ['id','value','quote','epistemic','valid_to']} for f in unit['facts']]),ensure_ascii=False,sort_keys=True))
