"""Fact-state barriers; soft intent hints; event-bound evidence coverage."""
import copy,re,time,math
from .contract import normalize
from .policy import HISTORY,CURRENT,EXAMPLE,ACTUAL,VALUE_FIELDS,SCOPED_FIELDS
from .index import features,rule_score,lexical
from .extraction import EVENT_WORDS
from .identity import resolve_scope

def event_key(label):
    return re.sub(r'(?:失败|故障|异常|中断)$','',re.sub(r'[\W_的]+','',label))

def hints(text):
    fields=[]
    checks=[('contact_phone',r'电话|手机号|手机号码|联络号码|联系人.{0,4}(?:号码|电话)|拨打|通话'),
        ('other',r'邮箱|电子邮件|邮件.{0,4}地址|收件(?:.{0,4}地址)?|email|错误(?:码|标识)|退出码|返回.{0,5}(?:错误|标识)|产出|生成|输出文件|执行结果'),
        ('service_port',r'端口|监听|TCP'),('archive_path',r'目录|路径|文件夹|归档|存储位置|磁盘位置|存放'),
        ('reminder_time',r'几点|钟点|时刻|时分|通知时间|提醒时间|提醒状态|通知状态|通知时点|通知时段|简报时间|日报时间'),
        ('preference',r'偏好|习惯|风格|顺序|组织|先.{0,6}(?:呈现|写|给)|(?:补|加|展示|展开).{0,6}(?:图片|趋势图|步骤)|(?:图片|趋势图|步骤).{0,6}(?:补|加|展示|展开)|如何.{0,6}(?:答复|回答|说明)|何时补'),
        ('incident_cause',r'原因|根因|为什么|为何|起因|触发点|诱因|查清|查明|确认|结论|定位(?:状态|进展|处于)|查到哪|漏.{0,6}哪|哪.{0,6}漏'),
        ('incident_solution',r'处理|修复|修好|修正|解决|采取|恢复(?:办法|操作|可用|成功)|哪.{0,5}(?:动作|调整|办法)|做.{0,4}(?:一步|操作)'),
        ('incident_rule',r'下次|今后|以后|再次|防止|防错|避免|必须|不能放过|验收条件|检查要求'),
        ('deployment_state',r'部署|上线|发布|投入使用|可用范围|能不能使用|能否使用|装上|当前能用|覆盖哪|哪个区域|哪台.*可用')]
    for field,pattern in checks:
        if re.search(pattern,text,re.I):fields.append(field)
    if re.search(r'手册|示例|演示|教学|说明文档',text) and '时间' in text and not re.search(r'耗时|执行时间|持续时间',text):
        if 'reminder_time' not in fields:fields.append('reminder_time')
    if re.search(r'(?:何时|什么时候|时间).{0,8}(?:通知|提醒|日报|早报)|(?:通知|提醒|日报|早报).{0,8}(?:时间|何时|什么时候)',text):
        if 'reminder_time' not in fields:fields.append('reminder_time')
    # A lexical action such as '展开规则' in a preference is not an incident.
    topics=[t for t in EVENT_WORDS if t in text]
    # Configuration lifecycle words describe the query's background; they do
    # not request a business incident's cause or repair without such a subject.
    scalar=any(f in VALUE_FIELDS for f in fields)
    business=bool(re.search(r'(?:上传|导出|登录|同步|备份|解析|渲染|编译|下载|导入|支付|重连)(?:失败|故障|中断|异常|问题)?',text))
    if scalar and not business:fields=[f for f in fields if not f.startswith('incident_')];topics=[]
    if not topics and 'preference' in fields:fields=[f for f in fields if not f.startswith('incident_')]
    if not topics and any(f in fields for f in list(VALUE_FIELDS)+['deployment_state','other']):fields=[f for f in fields if not f.startswith('incident_')]
    return fields,topics

def intent(query):
    parts=[s.strip() for s in re.split(r'[，,；;。]|另外|另加|再加|以及',query) if s.strip()]
    requests=[];scope_parts=[];context='';context_fields=[]
    for part in parts:
        if re.search(r'^(?:别|不要|勿|不能|不应).{0,5}(?:把|拿|因为|引用|借用|套用|混用|采用|沿用)|^(?:请)?与.+(?:区别|区分)|^(?:不接受|禁止|不可).*(?:顶替|替代|套用)',part):continue
        scope_parts.append(part)
        fs,ts=hints(part)
        if ts:context=part
        if fs:context_fields=fs
        if re.search(r'(?:之后|以后|完成后|解决后|生效后|更正后|核对后|冲突后)$',part) and not re.search(r'什么|如何|怎样|哪个|吗|是否|给出|说明',part):continue
        if re.search(r'期间|的时候|时先|先不问|暂不问',part) and not re.search(r'吗|什么|多少|给出|能否|能给|能确认|可以确认',part):continue
        if not fs and context_fields and re.search(r'什么|多少|哪个|能否|能给|能确认|可以确认|是否|吗|安排',part):fs=context_fields
        if fs:requests.append(dict(fields=fs,topics=ts or hints(context)[1],text=part if ts else context+'；'+part))
    fields=list(dict.fromkeys(f for r in requests for f in r['fields']));topics=list(dict.fromkeys(t for r in requests for t in r['topics']))
    return dict(field=fields[0] if fields else None,fields=fields,hints=fields,topics=topics,requests=requests,scope_text='；'.join(scope_parts),
        historical=bool(re.search(HISTORY+'|第一次|初次|调整前|更改前|更换前|迁移前',query)) and not bool(re.search(CURRENT,query)),
        example=bool(re.search(EXAMPLE+'|手册|示范',query)) and not bool(re.search(ACTUAL,query)),require_confirmed=False)

def present_fact(f,blocked):
    if f['field'] in blocked:return None
    out=copy.deepcopy(f)
    # Drop only a clause carrying a prohibited value. Never erase a sibling
    # because another clause of its source had a pending clock or port.
    if blocked:
        for field,literals in blocked.items():
            for value in literals:
                if not value or value not in out['quote']:continue
                if f['field'] in VALUE_FIELDS or (f['field']=='other' and f['topic']=='email'):
                    pieces=re.split(r'[，,；;。]',out['quote'])
                    safe=[p for p in pieces if f['value_text'] in p and value not in p]
                    if not safe:return None
                    out['quote']=safe[0]
                else:return None
    return out

def retrieve(store,query,at,registry,vectors,*,mode='repaired',model=None,cap=4,allowed_unit_ids=None,max_units=4,request_plan=None,scope=None,weights=(.65,.20,.10,.05,.25),ranker=None):
    started=time.perf_counter_ns();d=intent(query);ranking_meta=dict(method='rules',matching_ms=0)
    if request_plan is not None:
        d['fields']=list(dict.fromkeys(r['field'] for r in request_plan if r['field'] not in ['any','credential']))
        d['requests']=[dict(fields=[r['field']],topics=[],text=query,event_labels=[r['event']] if r.get('event') else []) for r in request_plan]
    p,e=(scope or resolve_scope(query,registry)[:2]);ps=[p] if p else [];es=[e] if e else []
    def output(rows,chosen,reason,blocked=None):
        facts=[];seen=set()
        for row in chosen:
            # Keep entire incident C/S/R bundles inside an event; downstream
            # must never borrow a cause from a different bundle.
            for f in sorted(row['facts'],key=lambda f:(f['field'] not in d['fields'],f['id'])):
                if f['id'] not in seen:facts.append(f);seen.add(f['id'])
        return dict(abstain=not facts,reason=reason,ranked=rows,answer_facts=facts,decision=d,
            decision_ms=(time.perf_counter_ns()-started)/1e6,blocked_fields=blocked or {},selected_unit_ids=[r['unit_id'] for r in chosen],ranking=ranking_meta)
    if len(ps)!=1 or len(es)!=1:return output([],[],'对象范围不明确')
    units=[u for u in store.units(at,d['historical'],ps[0],es[0]) if (u['kind']=='example')==d['example']]
    blocked={}
    if not d['historical'] and not d['example']:
        for row in store.db.execute('SELECT p.field FROM pending_updates p JOIN controls c ON c.source_id=p.source_id WHERE p.project=? AND p.entity=? AND p.seq<=? AND (p.resolved_at IS NULL OR p.resolved_at>?) AND c.excluded=0 AND c.deleted=0 AND (c.withdrawn_at IS NULL OR c.withdrawn_at>?)',(ps[0],es[0],at,at,at)):blocked[row['field']]='值尚待明确'
    if not d['historical']:
        for field in VALUE_FIELDS:
            if len({f['value'] for u in units for f in u['facts'] if f['field']==field})>1:blocked[field]='现有值冲突，尚无结论'
    literals={field:{f['value_text'] for u in units for f in u['facts'] if f['field']==field} for field in blocked}
    # Event label selection is independent of whether an intent word matched.
    # Literal specific labels distinguish two named uploads; generic categories
    # constrain which event bundles can appear in a single-event answer.
    scope_text=d['scope_text'] or query
    compact=re.sub(r'[\W_的]+','',scope_text)
    labels={f['topic'] for u in units for f in u['facts'] if f['field'] in SCOPED_FIELDS and f['topic']}
    capabilities={f['topic'] for u in units for f in u['facts'] if f['field']=='deployment_state'}
    named={t for t in labels if (len(event_key(t))>2 or t in capabilities) and event_key(t) in compact}
    if named:
        named={t for t in named if not any(t!=x and t in x for x in named)}
    if request_plan is not None:
        named={r['event'] for r in request_plan if r.get('event') and r['field'] in SCOPED_FIELDS}
        d['topics']=[]
    for req in d['requests'] if request_plan is None else []:
        compact_req=re.sub(r'[\W_的]+','',req['text'])
        req['event_labels']=[t for t in named if event_key(t) in compact_req]
    if len(d['topics'])==1 and not named:
        matching={t for t in labels if d['topics'][0] in t}
        if len(matching)>1:return output([],[],'同类事件不止一个，请明确具体事件',blocked)
    ranked=[]
    for u in units:
        if allowed_unit_ids is not None and u['id'] not in allowed_unit_ids:continue
        incident=any(f['field'] in SCOPED_FIELDS for f in u['facts'])
        if incident and (d['topics'] or named):
            event_topics={f['topic'] for f in u['facts']}
            if named and not event_topics&named:continue
            if not named and not any(t in label for t in d['topics'] for label in event_topics):continue
        # Incident-only questions get event evidence, not stray configurations.
        if d['topics'] and d['fields'] and all(f.startswith('incident_') for f in d['fields']) and not incident:continue
        facts=[g for f in u['facts'] if (g:=present_fact(f,literals)) is not None]
        if not facts:continue
        x=features(query,u,vectors,cap)
        x[3]=float(any(f['field'] in d['fields'] for f in facts)) if d['fields'] else 0
        x[7]=float(bool(d['fields']))
        residual=query
        for name in registry['projects']+registry['entities']:residual=residual.replace(name,'')
        # Quotes carry symptoms that a short stored solution value may omit.
        # Score source-local overlap after removing shared scope names.
        basis=[float(x[0]),float(x[2]),float(x[3]),float(x[4]),lexical(residual,' '.join(f['quote'] for f in facts))]
        score=sum(w*v for w,v in zip(weights,basis))
        ranked.append(dict(unit_id=u['id'],source_id=u['source_id'],score=score,features=basis,facts=facts))
    if ranker and ranked:
        original={r['unit_id'] for r in ranked};scores,meta=ranker(query,copy.deepcopy(ranked))
        if set(scores)!=original or any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in scores.values()):raise ValueError('ranker must score the identical legal candidate set')
        for row in ranked:row['base_score']=row['score'];row['score']=scores[row['unit_id']]
        ranking_meta={**meta,'candidate_ids':sorted(original)}
    ranked.sort(key=lambda r:(-r['score'],r['unit_id']))
    if request_plan is not None:
        from .decision import choose_units
        chosen=choose_units(ranked,request_plan,max_units)
        relevant_blocked={f:s for f,s in blocked.items() if f in d['fields']}
        reason='有来源证据'+('；'+'；'.join(field+'：'+state for field,state in sorted(relevant_blocked.items())) if relevant_blocked else '')
        return output(ranked,chosen,reason,relevant_blocked)
    chosen=[];chosen_ids=set()
    def add(row):
        if row and row['unit_id'] not in chosen_ids and len(chosen)<max_units:chosen.append(row);chosen_ids.add(row['unit_id'])
    # Cover each explicitly requested facet. Hints bias evidence selection; a
    # missing/blocked hint cannot prevent another facet from being searched.
    for req in d['requests'] or [dict(fields=d['fields'],topics=d['topics'])]:
        for field in req['fields']:
            def matches(f):
                if f['field']!=field:return False
                if request_plan is not None:return not req.get('event_labels') or f['topic'] in req['event_labels']
                if field not in SCOPED_FIELDS:return True
                return f['topic'] in req['event_labels'] if req.get('event_labels') else not req['topics'] or any(t in f['topic'] for t in req['topics'])
            choices=[r for r in ranked if any(matches(f) for f in r['facts'])]
            if choices:add(choices[0])
    if not chosen and ranked and (request_plan is None or any(r['field']=='any' for r in request_plan)):add(ranked[0])
    # Add a close semantic backup only when intent was not recognized. Explicit
    # requests do not force three mostly irrelevant entries into every answer.
    if not d['fields'] and len(ranked)>1 and ranked[0]['score']-ranked[1]['score']<=.04:add(ranked[1])
    reason='有来源证据'
    relevant_blocked={f:s for f,s in blocked.items() if not request_plan or f in d['fields']}
    if relevant_blocked:reason+='；'+ '；'.join(field+'：'+state for field,state in sorted(relevant_blocked.items()))
    return output(ranked,chosen,reason,relevant_blocked)
