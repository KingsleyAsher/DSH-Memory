"""Route queries to existing event identities; never create facts or aliases.

The caller supplies only scoped, time-visible frames. Explicit aliases come
from the operation ledger. A lexical fallback can nominate one uniquely
supported event, but cannot authorize a version change or a stored alias.
"""
import collections
import re
from .views import canonical_event

GENERIC = {'提醒','通知','检查','时间','时候','现在','当前','安排','什么','哪天','几点',
           '哪个','那个','这条','那条','之前','原来','还是','是否','已经','怎么','方案',
           '问题','原因','状态','继续','记录','要求','请问','一下','有没有','多少'}


def terms(text):
    text = canonical_event(text).lower()
    return {text[i:i+2] for i in range(len(text)-1)} - GENERIC


def groups_for(frames, category=None):
    groups = {}
    for frame in frames:
        if frame.get('category') not in ['event','reminder']:
            continue
        if category and frame.get('category') != category:
            continue
        event = canonical_event(frame.get('topic',''))
        if not event or event in GENERIC:
            continue
        group = groups.setdefault(event, dict(aliases={event}, texts=[], ids=[]))
        group['aliases'].update(canonical_event(s) for s in frame.get('event_aliases',[])
                                if isinstance(s,str) and len(canonical_event(s)) >= 2
                                and canonical_event(s) not in GENERIC)
        # Quotes can contain adjacent, unselected events. Route using selected
        # values only, never borrow another event from a whole source quote.
        group['texts'].append(frame.get('value_text',frame.get('value','')))
        if frame.get('record_kind')=='operation' and frame.get('operation_action')=='retract':
            group['texts'].extend(frame.get('operation_target_values',[]))
        group['ids'].append(frame['id'])
    return groups


def match_events(question, frames, category=None):
    groups = groups_for(frames, category)
    if not groups:
        return [], dict(method='legacy', ambiguous=False, candidates=[])
    body = canonical_event(question)
    matched = [(alias,event) for event,g in groups.items() for alias in g['aliases']
               if alias and alias in body]
    # A shorter registered name inside a longer literal name is not a second
    # event request. Distinct full names explicitly asked together are retained.
    matched = [(alias,event) for alias,event in matched
               if not any(alias != other and alias in other for other,_ in matched)]
    if matched:
        by_alias = collections.defaultdict(set)
        for alias,event in matched:
            by_alias[alias].add(event)
        ambiguous = any(len(events)>1 for events in by_alias.values())
        events = sorted({event for _,event in matched})
        return ([] if ambiguous else events), dict(method='registered_name', ambiguous=ambiguous,
                                                   candidates=events)
    query = terms(question)
    inventories = {event:terms(' '.join([event,*g['aliases'],*g['texts']])) for event,g in groups.items()}
    frequency = collections.Counter(term for inventory in inventories.values() for term in inventory)
    ranked = []
    for event,inventory in inventories.items():
        hit = query & inventory
        unique = {term for term in hit if frequency[term] == 1}
        score = sum(1/frequency[term] for term in hit)
        if len(unique) >= 2:
            ranked.append((score,len(unique),event,sorted(unique)))
    ranked.sort(reverse=True)
    if ranked and (len(ranked)==1 or ranked[0][0]-ranked[1][0] >= 1):
        _,_,event,anchors = ranked[0]
        return [event], dict(method='selected_value_anchors', ambiguous=False, candidates=[event],
                            anchors=anchors, support_ids=groups[event]['ids'])
    return [], dict(method='unresolved', ambiguous=len(ranked)>1,
                    candidates=[r[2] for r in ranked])


def attach_aliases(frames, aliases):
    """Attach ledger-validated aliases without changing the selected values."""
    by_event = collections.defaultdict(list)
    for item in aliases:
        canonical = canonical_event(item.get('canonical',''))
        alias = item.get('alias')
        if canonical and isinstance(alias,str) and len(alias)<=80:
            by_event[canonical].append(item)
    for frame in frames:
        if frame.get('category') in ['event','reminder']:
            candidates=by_event.get(canonical_event(frame.get('topic','')),())
            frame['event_aliases'] = sorted({item['alias'] for item in candidates
                if (not item.get('event_id') or item['event_id']==frame.get('event_id'))
                and (not item.get('kind') or item['kind']==frame.get('kind'))})[:12]
