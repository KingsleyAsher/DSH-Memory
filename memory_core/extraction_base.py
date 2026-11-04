"""Bounded local extraction + literal anchors + automatic coverage check.

No labels, query answers or future messages enter this module. The literal
recognizer deliberately covers a limited set of configuration formats.
"""
import copy
import re

from .contract import (CHINESE_TIME, EXAMPLE, PATH, PHONE, PROMPT, SCHEMA, TIME, TOPICS,
                      normalize, validate_fact, validate_shape)


def sentences(text):
    return [m.group().strip() for m in re.finditer(r'[^。！？\n；;]+[。！？；;]?', text) if m.group().strip()]


def clauses(text):
    return [m.group().strip() for m in re.finditer(r'[^，,。！？\n；;]+', text) if m.group().strip()]


def local_kind(text, value, quote=None):
    pos = text.find(value)
    if pos < 0:
        return 'fact'
    sentence = next((s for s in sentences(text) if value in s), quote or text)
    prefix = sentence[:sentence.find(value)]
    # A later actual-value marker starts a new context inside a mixed sentence.
    ex = list(re.finditer(EXAMPLE, prefix))
    actual = list(re.finditer(r'实际|正式|线上|生产环境|真实设置', prefix))
    if ex and (not actual or ex[-1].start() > actual[-1].start()):
        return 'example'
    if re.search(r'不是.*(?:实际|正式)|不适用于|都是样例|是演示值', sentence) and re.search(EXAMPLE, sentence):
        return 'example'
    return 'fact'


def make_fact(field, value, quote, *, kind='fact', topic='', epistemic='stated'):
    return {'field': field, 'topic': topic, 'value_text': value, 'quote': quote,
            'kind': kind, 'epistemic': epistemic}


def rejected_literal(clause, value):
    before, _, after = clause.partition(value)
    return bool(re.search(r'(?:取消|撤销|作废|不再用|不是|别再用|旧时间|旧值)\s*$', before)
                or re.match(r'\s*(?:那个|那条|那版)?(?:旧时间|旧值|取消|作废|撤销|不用了|还太早|还太晚)', after)
                or re.search(r'改(?:成|到|为|用)|调整为|换成', after))


def anchors(text):
    result = []
    for sentence in sentences(text):
        if sentence.endswith(('？', '?')) and not re.search(r'设为|定为|改为|改到|请用', sentence):
            continue
        port_context=False
        for clause in clauses(sentence):
            patterns = []
            if re.search(r'通知|提醒|早报|日报|推送|简报|钟点|时间', sentence):
                patterns.append(('reminder_time', '(?:'+TIME+'|'+CHINESE_TIME+')'))
            if re.search(r'归档|目录|保存|存放|附件|路径', sentence):
                patterns.append(('archive_path', PATH))
            if re.search(r'电话|手机|联系方式|联系号码', sentence):
                patterns.append(('contact_phone', PHONE))
            if re.search(r'端口|监听',clause):port_context=True
            elif re.search(r'提醒|通知|归档|目录|路径|电话|手机',clause):port_context=False
            if port_context and (re.search(r'端口|监听',clause) or re.match(r'\s*(?:更正|改成|改为|调整为|换成|以|新的.{0,4}号)',clause)):
                patterns.append(('service_port', r'(?<![\d:/\\])\d{2,5}(?![\d:/\\])'))
            for field, pattern in patterns:
                for m in re.finditer(pattern, clause):
                    value = m.group().strip().rstrip(' .')
                    if field == 'reminder_time' and not clock_reference(sentence, clause, m):
                        continue
                    if rejected_literal(clause, value):
                        continue
                    if field == 'service_port' and not (0 < int(value) <= 65535):
                        continue
                    candidate = make_fact(field, value, clause, kind=local_kind(text, value))
                    if re.search(r'计划|打算|拟(?:设|改|用)|下周|明天',clause) and not re.search(r'已(?:经)?|当前|现在',clause):candidate['epistemic']='planned'
                    try:
                        validate_fact(text, candidate)
                        result.append(candidate)
                    except ValueError:
                        pass
    for field in ['reminder_time', 'archive_path', 'service_port', 'contact_phone']:
        for kind in ['fact', 'example']:
            updates = [f for f in result if f['field'] == field and f['kind'] == kind and re.search(r'改(?:成|到|为|用)|调整(?:为|到)|换(?:成|到)|以.+为准', f['quote'])]
            if updates:
                keep = {normalize(field, f['value_text']) for f in updates}
                result = [f for f in result if f['field'] != field or f['kind'] != kind or normalize(field, f['value_text']) in keep]
    return result


def clock_reference(sentence, clause, match):
    """Literal occurrence alone is not evidence of a clock setting."""
    value=match.group()
    if re.fullmatch(TIME,value):return True
    prefix=clause[:match.start()]
    # Degree complements (长一点、晚一点) are not the literal hour 一点.
    if re.search(r'(?:长|短|多|少|早|晚|快|慢|大|小|近|远|详细|清楚|省)\s*$',prefix):return False
    if re.search(r'凌晨|早上|上午|中午|下午|傍晚|晚上|晚间',value):return True
    return bool(re.search(r'提醒|推送|钟点|时间|早报|日报|简报|通知(?!书)',clause)
                and not re.search(r'缴费通知|通知书|通知单',clause))


def uncovered_clauses(text, proposals):
    """A cheap review trigger, not a rule that turns every clause into memory."""
    values=[f.get('value_text','') for p in proposals if isinstance(p,dict)
            for f in p.get('facts',[]) if isinstance(f,dict)]
    important=r'必须|不能|不要|别|仅|只(?:能|在|有)|不再|撤回|更正|确认|查明|已(?:经)?|尚未|待定|决定|以后|每次|需要'
    out=[]
    for sentence in sentences(text):
        for clause in clauses(sentence):
            if not re.search(important,clause) or len(clause)<7:continue
            # Quote-only background does not count as an extracted assertion.
            if any(v and (clause in v or v in clause) for v in values):continue
            out.append(clause)
    return out[:8]


def required_fields(text):
    fields = {f['field'] for f in anchors(text)}
    checks = [('deployment_state', r'部署|上线|投入使用'),
              ('incident_cause', r'原因|根因|定位到|查明|尚未查清'),
              ('incident_solution', r'修复|修正|解决|后来.*(?:恢复|通过)|更新.*后|改为.*后'),
              ('preference', r'(?:回复|答复|回答|输出).*(?:希望|先|不要|别|尽量|喜欢)|(?:喜欢|希望).*(?:回复|答复|回答|输出)'),
              ('incident_rule', r'(?:以后|下次|今后).*(?:必须|不要|不能|核对|检查|验证)')]
    fields.update(field for field, pattern in checks if re.search(pattern, text))
    return fields


def change_fields(text):
    """Notice attempted changes even when their values are unsupported."""
    fields = set()
    patterns = [('reminder_time', r'提醒|通知|简报|钟点'), ('archive_path', r'归档|目录|路径'),
                ('service_port', r'端口|监听'), ('contact_phone', r'电话|手机|联系方式')]
    for clause in clauses(text):
        if re.search(r'改(?:成|到|为|用)|更正|调整(?:为|到)|换(?:成|到)|以.+为准', clause):
            fields.update(field for field, pattern in patterns if re.search(pattern, clause))
    return fields


def state_fallbacks(text):
    """Only explicit negative/unknown/preference statements, retaining full quote."""
    result = []
    # Semicolons often carry the condition of a preference. Keep that together.
    paragraphs = [m.group().strip() for m in re.finditer(r'[^。！？\n]+[。！？]?', text) if m.group().strip()]
    for sentence in paragraphs:
        source_topics = [t for t in TOPICS if t in text]
        topic = next((t for t in TOPICS if t in sentence), source_topics[0] if len(source_topics) == 1 else '')
        kind = 'example' if re.search(EXAMPLE, sentence) and not re.search(r'实际|正式|线上|生产环境', sentence) else 'fact'
        if re.search(r'原因|根因', sentence) and re.search(r'未.*(?:查|确认|定位)|没.*(?:查|确认)|尚不明确|不确定|不能确定|未知|待查', sentence):
            result.append(make_fact('incident_cause', sentence, sentence, topic=topic, kind=kind, epistemic='unknown'))
        if topic and re.search(r'怀疑|猜测|只是推测|只是可能|可能是', sentence):
            result.append(make_fact('incident_cause', sentence, sentence, topic=topic, kind=kind, epistemic='hypothesis'))
        if re.search(r'部署|上线|投入使用', sentence) and re.search(r'尚未|还没|没有|并未|未曾|暂未', sentence):
            result.append(make_fact('deployment_state', sentence, sentence, kind=kind))
        if re.search(r'(?:回复|答复|回答|输出).*(?:希望|先|不要|别|尽量|喜欢)|(?:喜欢|希望).*(?:回复|答复|回答|输出)', sentence):
            result.append(make_fact('preference', sentence, sentence))
        if re.search(r'(?:暂停|取消|停止|不再).*(?:提醒|通知)|(?:提醒|通知).*(?:暂停|取消)|暂不设', sentence) and not re.search(TIME, sentence):
            result.append(make_fact('reminder_time', sentence, sentence))
    return result


def reconcile(text, proposals):
    accepted, diagnostics = [], []
    literal = anchors(text)
    by_field = {}
    for f in literal:
        by_field.setdefault(f['field'], []).append(f)
    for proposal in proposals:
        try:
            validate_shape(proposal)
        except (ValueError, TypeError) as exc:
            diagnostics.append({'reason': str(exc)})
            continue
        for raw in proposal['facts']:
            f = copy.deepcopy(raw)
            try:
                if (isinstance(f, dict) and f.get('field') in ['incident_cause', 'incident_solution', 'incident_rule', 'preference', 'deployment_state']
                        and isinstance(f.get('quote'), str) and f['quote'] and f['quote'] in text
                        and isinstance(f.get('value_text'), str) and f['value_text'] not in f['quote']):
                    f['value_text'] = f['quote']
                validate_fact(text, f)
                f['kind'] = local_kind(text, f['value_text'], f['quote'])
                if f['field'] in ['reminder_time', 'archive_path', 'service_port', 'contact_phone']:
                    # Exact literal recognition bounds the model's configuration claims.
                    choices = [a for a in by_field.get(f['field'], []) if normalize(f['field'], a['value_text']) == normalize(f['field'], f['value_text'])]
                    if normalize(f['field'], f['value_text']) != '__unset__' and not choices:
                        raise ValueError('literal_is_old_negated_or_out_of_field')
                    if choices:
                        f['quote'], f['kind'] = choices[0]['quote'], choices[0]['kind']
                        f['epistemic']=choices[0]['epistemic']
                    f['topic'] = ''
                if f['field'] == 'incident_cause':
                    # The model must not promote a substring of a hypothesis
                    # into certainty by dropping its surrounding qualifier.
                    context = next((s for s in sentences(text) if f['quote'] in s), f['quote'])
                    f['quote'] = context
                    if re.search(r'怀疑|猜测|可能|推测|待验证', context):
                        f['epistemic'] = 'hypothesis'
                    if re.search(r'原因|根因', f['value_text']) and re.search(r'未|没|尚不|不确定|不能确定|未知', f['value_text']):
                        f['epistemic'] = 'unknown'
                if f['field'].startswith('incident_'):
                    recognized = [t for t in TOPICS if t in f['topic'] or t in f['quote']]
                    if not recognized:
                        source_topics = [t for t in TOPICS if t in text]
                        if len(source_topics) == 1:
                            recognized = source_topics
                    if len(recognized) == 1:
                        f['topic'] = recognized[0]
                else:
                    f['topic'] = ''
                if f['field'] == 'deployment_state' and re.search(r'尚未|还没|没有|并未|暂未', f['quote']):
                    f['epistemic'] = 'stated'
                    f['value_text'] = f['quote']
                accepted.append(f)
            except (ValueError, TypeError, KeyError) as exc:
                diagnostics.append({'reason': str(exc), 'fact': raw})
    # Literal coverage is independent of whether the model happened to return it.
    accepted.extend(literal)
    # Unknown state and a suspected cause are separate facts. A preference's
    # conditional tail must survive even if the model returned its first clause.
    for fallback in state_fallbacks(text):
        if fallback['field'] == 'preference':
            accepted = [f for f in accepted if not (f['field'] == 'preference' and f['quote'] in fallback['quote'])]
            accepted.append(fallback)
        elif not any(f['field'] == fallback['field'] and f['kind'] == fallback['kind'] and (fallback['epistemic'] not in ['unknown', 'hypothesis'] or f['epistemic'] == fallback['epistemic']) for f in accepted):
            accepted.append(fallback)
    deployment = [f for f in accepted if f['field'] == 'deployment_state' and f['kind'] == 'fact']
    if deployment:
        paragraphs = [m.group().strip() for m in re.finditer(r'[^\n]+', text) if m.group().strip()]
        packet = next((p for p in paragraphs if all(f['quote'] in p for f in deployment)), None)
        if packet:
            accepted = [f for f in accepted if f not in deployment]
            accepted.append(make_fact('deployment_state', packet, packet, epistemic='stated' if re.search(r'未|没|已.*部署|已.*上线', packet) else deployment[0]['epistemic']))
    unique = {}
    for f in accepted:
        key = (f['field'], f['kind'], f['topic'], normalize(f['field'], f['value_text']))
        unique.setdefault(key, f)
    return list(unique.values()), diagnostics


def extract(source, prior, call):
    """At most two local calls; retries depend only on source-visible coverage."""
    if source['role'] not in ['user', 'tool']:
        return {'facts': [], 'diagnostics': [], 'missing_fields': [], 'calls': []}
    payload = {'current': source, 'prior': prior}
    out = call(PROMPT, payload, SCHEMA, max_tokens=1536)
    calls, proposals = [out], [out['value']]
    facts, diagnostics = reconcile(source['text'], proposals)
    missing = sorted(required_fields(source['text']) - {f['field'] for f in facts})
    uncovered = uncovered_clauses(source['text'],proposals)
    malformed = not isinstance(out['value'], dict)
    if missing or malformed or uncovered:
        retry = call(PROMPT, {**payload, 'coverage_review': {
            'missing_fields': missing, 'uncovered_clauses':uncovered,
            'already_proposed':out['value'],
            'instruction': '逐命题复核可能遗漏的可复用信息，仅补提尚未明确表达的点；不是每句都应保存。保留对象、否定、条件与状态，逐字引用。不要复述已有点，字段名和触发词不是事实依据，没有遗漏则留空。'}}, SCHEMA, max_tokens=1536)
        calls.append(retry)
        proposals.append(retry['value'])
        facts, diagnostics = reconcile(source['text'], proposals)
    pending = sorted(change_fields(source['text']) - {f['field'] for f in facts if f['kind'] == 'fact'})
    return {'facts': facts, 'diagnostics': diagnostics, 'pending_fields': pending,
            'missing_fields': sorted(required_fields(source['text']) - {f['field'] for f in facts}),
            'calls': calls}
