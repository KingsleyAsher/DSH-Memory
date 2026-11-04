"""Event reminder identity and conservative, source-grounded change gates.

The model still chooses a target. These helpers never pick the newest clock,
and never turn every reminder in a project into a single configuration slot.
"""
import re

from .contract import TIME, CHINESE_TIME


REMINDER = r'提醒|通知|闹钟'
CHANGE = r'改到|改为|改成|改期|调整为|调整到|挪到|移到|延期|推迟|提前|取消|撤回|撤销|作废|不再沿用|不再提醒|不再通知|撤掉|先撤|新时间待定|时间未定'
NEGATED = r'(?:别|不要|不能|不必|不用|没有|并未|不是|并非|未|没|不)[^，。；;]{0,24}(?:改|调整|挪|移|延期|推迟|提前|取消|撤回|撤销|作废|撤掉)'
CONDITIONAL = r'如果|假如|要是|倘若|考虑|打算|计划|准备|可能.{0,8}(?:改|调整|挪|延期)|等.{0,8}(?:后|再)'
GENERIC = {'提醒', '通知', '闹钟', '时间', '行程', '待办', '事项', '安排', '一次性', '项目', '日期',
           '两次', '本次', '这次', '此次', '提醒状态', '提醒执行状态', '提醒设置状态', '提醒写入状态',
           '执行状态', '创建状态', '设置状态', '写入状态', '提醒服务', '通知服务'}
OPERATIONS = [('核对',r'核对|核验|核|验'),('检查',r'检查|查验|查'),
              ('归还',r'归还|退还'),('递交',r'递交|提交|交'),('发送',r'发送|发给|发')]
CONTAINERS = r'(?:名单|照片|草稿)$'
QUALIFIERS = r'(?:长焦|广角|备用|原装)+'
DATE = r'(?:\d{1,2}|[一二三四五六七八九十]{1,3})月(?:\d{1,2}|[一二三四五六七八九十]{1,3})(?:日|号)'
FREQUENCY = r'每天|每日|每周|每月|每年|每隔|每次|一次|两次|单次|重复|频率|次数|周期'


def reminder_axis(record,attribute=''):
    """Classify the selected assertion, never borrow a clock from its quote."""
    value=record.get('value_text',record.get('value',''))
    attr=attribute or record.get('attribute','')
    if re.search(r'创建状态|执行状态|创建要求|执行要求|创建尝试|服务|回执|持久化|观测|证据|结果|失败',attr) or re.search(r'接口|回执|持久化|任务编号|创建请求|创建尝试|试着创建|通知触发|实际执行|创建成功|已创建|未创建|没有创建|超时',value):
        return 'execution'
    clock=bool(re.search(TIME+'|'+CHINESE_TIME+'|'+DATE,value))
    if not clock and (re.search(r'频率|重复|次数|周期|单次',attr) or re.search(FREQUENCY,value)):
        return 'repeat'
    if clock or re.search(r'时间|日期|时刻|钟点',attr) or re.search(r'取消|撤回|撤销|待定|时间未定|时间没定|提醒我|通知我|叫我',value):
        return 'schedule'
    return 'unknown'


def change_axis(clause):
    if re.search(r'(?:频率|重复|次数|周期).{0,12}(?:改|调整|取消)|(?:改为|改成|调整为|调整成).{0,12}(?:'+FREQUENCY+r')',clause):
        return 'repeat'
    return 'schedule'


def positive_change_parts(text):
    pieces=[p.strip() for p in re.findall(r'[^。；;！？!?\n，,]+[。；;！？!?\n，,]*',text) if p.strip()]
    result=[]
    for i,part in enumerate(pieces):
        if not re.search(CHANGE,part) or re.search(NEGATED+'|'+CONDITIONAL,part):continue
        # A past cancellation or the noun "confirmed rescheduling record" is
        # evidence about an existing state, not a new command to mutate it.
        if re.search(r'(?:已经|早已|先前已|此前已)(?:被)?(?:取消|撤销|撤回|改期|作废)(?:的|过|了)|(?:继续|仍|保持|沿用|维持).{0,16}(?:已确认|既定).{0,16}(?:改期|安排|记录)|已确认的(?:改期|取消|撤回)(?:记录|决定|安排)',part):continue
        if re.search(r'是否|要不要|能否|会不会|是不是|[？?]|吗[，,。；;]*$',part):continue
        if i+1<len(pieces) and re.fullmatch(r'(?:这样)?(?:可以|好|行|对|合适)(?:吗|么|不)[？?。！!]*',pieces[i+1]):continue
        prior=pieces[i-1] if i and not re.search(r'[。；;！？!?\n]',pieces[i-1]) else ''
        if prior and re.search(CONDITIONAL,prior):continue
        result.append((part.strip('。；;！？!?\n，,'),prior.strip('，,')))
    return result


def pending_role_compatible(text,target,attribute=''):
    axis=reminder_axis(target,attribute)
    return any(axis==change_axis(part) for part,_ in positive_change_parts(text))


def reference_only_reminder(text):
    return (not positive_change_parts(text) and bool(re.search(
        r'旧时间|旧时刻|旧便签|便签.{0,24}(?:还写|写着|旧)|早先.{0,30}(?:已经|已)取消|已经取消的',text)))


def non_mutating_reminder_reference(source,record,target):
    """Sanitize an erroneous lifecycle ref only for explicit retain/history.

    Keep the assertion/proof and audit the reference; never infer a new clock,
    slot, or successor. Other ungrounded references still fail closed.
    """
    if source.get('role')!='user':return False
    quote=record.get('quote','') or next((e['quote'] for e in record.get('evidence',[]) if e['source_id']==source['id']),'')
    if not quote or quote not in source['text'] or positive_change_parts(quote):return False
    keeping=reference_only_reminder(quote) or bool(re.search(r'继续按.{0,18}已确认|沿用.{0,18}(?:已确认|原|记录)|保持不变|维持原|照旧|不要.{0,8}(?:重试|补建|恢复)|别.{0,12}补建',quote))
    if not keeping:return False
    old=target.get('value_text',target.get('value',''))
    clocks=lambda text:{m.group() for m in re.finditer(TIME+'|'+CHINESE_TIME,text)}
    same_old_date=bool(set(re.findall(DATE,quote))&set(re.findall(DATE,old)))
    return names_reminder(quote,target) or same_old_date and bool(clocks(quote)&clocks(old))


def operation_purpose(text,target,label):
    """Bounded abbreviation: retain a complete object, never shared fragments.

    A label can carry a person's name before the actual object. Omitted prefix
    context must be present nearby, be a known modifier, or share an explicit
    old date; catalog-level uniqueness is still required by the caller.
    """
    found=False;body=compact(text)
    for alias,canonical in [('核验','核对'),('查验','检查'),('退还','归还'),('提交','递交')]:
        label=label.replace(alias,canonical)
    dates=set(re.findall(DATE,text)) & set(re.findall(DATE,' '.join(str(target.get(k,'')) for k in ['value','value_text','quote'])))
    for canonical,aliases in OPERATIONS:
        if canonical not in label:continue
        found=True;obj=re.sub(CONTAINERS,'',label.replace(canonical,'',1))
        for part in re.split(r'[。；;！？!?\n，,]',text):
            for match in re.finditer(aliases,part):
                # Take the whole noun phrase on either side of the operation,
                # stopping at grammatical/reminder/change boundaries.
                right=re.split(r'的|那条|那次|这条|这次|提醒|通知|闹钟|改到|改为|改成|移到|挪到|先取消|取消|先撤|撤回|待定',part[match.end():])[0]
                left=re.split(r'把|给|跟|与|关于|需要|请|叫我|提醒我|通知我',part[:match.start()])[-1]
                for raw in [right,left]:
                    anchor=re.sub(CONTAINERS,'',compact(raw))
                    if len(anchor)<2 or anchor in GENERIC or anchor in ['名单','照片','草稿'] or not obj.endswith(anchor):continue
                    prefix=obj[:-len(anchor)]
                    if not prefix or prefix in body or re.fullmatch(QUALIFIERS,prefix) or dates:
                        return True
    return False if found else None


def compact(text):
    return re.sub(r'[\W_的]+', '', text or '')


def reminder_label(record):
    label = compact(record.get('topic', ''))
    label = re.sub(r'(?:一次性|临时|具体日期)', '', label)
    label = re.sub(r'(?:提醒|通知|闹钟|钟点|时刻|时间|安排|设置|改期)+$', '', label)
    return label if len(label) >= 2 and label not in GENERIC else ''


def is_event_reminder(record, attribute=''):
    if record.get('field') != 'other' or record.get('kind', 'fact') != 'fact':
        return False
    if reference_only_reminder(record.get('value_text',record.get('value',''))):return False
    if record.get('category')=='reminder':
        return bool(reminder_label(record))
    text = ' '.join(str(record.get(k, '')) for k in ['topic', 'value_text', 'value', 'quote']) + ' ' + attribute
    return bool(re.search(REMINDER, text) and reminder_label(record))


def names_reminder(text, target):
    """A literal named purpose is a guard, not a semantic alias resolver."""
    label = reminder_label(target)
    body = compact(text)
    if not label:
        return False
    if label in body:
        return True
    purpose=operation_purpose(text,target,label)
    if purpose is not None:
        return purpose
    # "镜头归还" and "归还镜头" share the object and operation. One generic
    # shared operation such as "检查" cannot bind two different objects.
    words = {label[i:i+2] for i in range(len(label)-1)} - GENERIC
    hit = {w for w in words if w in body}
    return len(hit) >= 2 and len(hit) / max(1, len(words)) >= .4


def reminder_change_clauses(text, target):
    result = []
    for part,prior in positive_change_parts(text):
        if reminder_axis(target,target.get('attribute',''))!=change_axis(part):continue
        if prior and re.search(r'是否|要不要|能否|会不会|[？?]',prior) and not names_reminder(part,target):continue
        candidate=part
        if not names_reminder(candidate,target) and prior and len(prior)+len(part)<=160:
            # Only an unnamed continuation can inherit the previous purpose.
            # "A不变，B提醒改到..." names B; carrying A forward would create
            # a false pending obligation even when the model correctly picks B.
            subject=part[:re.search(CHANGE,part).start()].strip()
            subject=re.sub(r'^(?:请|麻烦|先|再|就|还是|把|给我|帮我)+','',subject)
            subject=re.sub(r'(?:先|就|还是|也|仍然|仍|再|暂时|暂且|现在|目前|已经|直接|统一|都)+$','',subject)
            if not re.fullmatch(r'(?:那|这)?(?:一)?(?:条|个|次)?(?:提醒|通知|闹钟|时间|时刻|日期|钟点)?',subject):continue
            candidate=prior+'，'+candidate
        if names_reminder(candidate, target):
            result.append(candidate)
    return result


def grounded_reminder_change(source, record, target):
    if source.get('role') != 'user' or record.get('field') != 'other':
        return False
    if record.get('kind') != 'fact' or record.get('epistemic') not in ['stated', 'unknown']:
        return False
    quote = record.get('quote', '')
    value = record.get('value_text', '')
    if not quote or quote not in source.get('text', '') or not value or value not in quote:
        return False
    clauses = reminder_change_clauses(quote, target)
    return any(value in c or c in value for c in clauses)


def reminder_requests(question, frames):
    """Bind named event reminders to other/event requests, not daily config."""
    if not re.search(REMINDER, question):
        return []
    labels = sorted({reminder_label(f) for f in frames if is_event_reminder(f)})
    labels = [s for s in labels if s]
    plural=bool(re.search(r'哪些|所有|全部|各|分别|两次|几条|几项|列出', question))
    literal=[s for s in labels if s in compact(question)]
    named=[s for s in labels if names_reminder(question,dict(topic=s))]
    from .query_events import match_events
    semantic_names,routing=match_events(question,frames,'reminder')
    if routing['method']!='legacy':
        if routing.get('ambiguous'):
            return [dict(id='r0',event='__ambiguous_reminder__',field='other',mode='value',label='提醒事项待明确',reminder_event=True)]
        if semantic_names:named=semantic_names
    if literal and not plural and not semantic_names:named=literal
    if len(named)>1 and not plural and routing['method']!='registered_name':
        return [dict(id='r0',event='__ambiguous_reminder__',field='other',mode='value',label='提醒事项待明确',reminder_event=True)]
    if not named and plural:
        named = labels
    mode='status' if re.search(r'状态|是否|已经|已设|创建|回执|执行',question) else 'value'
    return [dict(id='r'+str(i), event=s, field='other', mode=mode, label=s+'·提醒',
                 reminder_event=True) for i, s in enumerate(named)]


def reminder_evidence_strength(record, request):
    if not request.get('reminder_event'):
        return 0
    value=record.get('value_text','')
    if record.get('control'):
        return 2
    if request.get('mode')=='status':
        return int(bool(re.search(r'执行|设置|创建|回执|取消|待定|失败',value)))
    return int(bool(re.search(TIME+'|'+CHINESE_TIME+'|取消|撤回|作废|待定',value)))


def raw_reminder_inactive(store, source, fact, at):
    """Raw excerpts cannot regain a retired/pending reminder via a new label."""
    text = fact.get('value_text', '')
    for row in store.db.execute('SELECT * FROM facts WHERE source_id=?', (source['source_id'],)):
        old = dict(row)
        if not is_event_reminder(old):
            continue
        inactive = old['valid_to'] is not None and old['valid_to'] <= at
        pending = old['id'] in store._pending_claim_ids(at)
        if not inactive and not pending:
            continue
        # This source can still supply unrelated material. Re-extracting a
        # shorter clock or renaming the topic cannot bypass its old claim ID.
        shared_clock = set(re.findall(TIME+'|'+CHINESE_TIME, text)) & set(re.findall(TIME+'|'+CHINESE_TIME, old['quote']))
        selected_label=reminder_label(fact)
        clock_only=shared_clock and (fact.get('field')=='reminder_time' or not selected_label)
        if fact.get('field') in ['other','reminder_time'] and (names_reminder(text, old) or old['value_text'] in text or clock_only):
            return 'inactive_event_reminder'
    return None
