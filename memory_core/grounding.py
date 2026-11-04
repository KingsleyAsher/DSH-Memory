"""Grounded language proposals retain semantics; heuristics cannot relabel them."""
import copy,re
from .contract import validate_fact,normalize
from .policy import VALUE_FIELDS

def restore(source,base,outputs,deferred=None):
    text=source['text'];accepted=[];diagnostics=[]
    for output in outputs:
        v=output.get('value')
        if not isinstance(v,dict) or not isinstance(v.get('facts'),list):continue
        for raw in v['facts']:
            f=copy.deepcopy(raw)
            try:
                validate_fact(text,f)
                if source['role']=='tool' and f['field'].startswith('incident_'):raise ValueError('tool_is_observation')
                if f['field'] in VALUE_FIELDS:f['topic']=''
                if f['field']=='incident_cause' and f['epistemic']=='stated':
                    clauses=[c for c in re.split(r'[。；;，,\n]',f['quote']) if f['value_text'] in c]
                    if any(re.search(r'怀疑|猜测|推测|可能是',c) and not re.search(r'不是猜测|并非猜测|不再怀疑|撤回|收回',c) for c in clauses):raise ValueError('certainty_conflicts_with_quote')
                if f['field']=='reminder_time':
                    from .extraction_base import anchors
                    if normalize('reminder_time',f['value_text'])!='__unset__' and not any(
                        a['field']=='reminder_time' and normalize(a['field'],a['value_text'])==normalize(f['field'],f['value_text'])
                        for a in anchors(text)):
                        raise ValueError('not_a_source_clock_setting')
                if f['field'].startswith('incident_') or f['field']=='deployment_state':
                    if not f['topic'] or f['topic'] not in text:
                        # Keep evidenced content without assigning it to an
                        # unverified event. Generic points cannot satisfy a
                        # typed incident request or replace another event.
                        item=dict(reason='event_binding_deferred',fact=copy.deepcopy(f))
                        if deferred is not None:deferred.append(item)
                        diagnostics.append(item)
                        f['field']='other';f['topic']=''
                accepted.append(f)
            except (ValueError,TypeError,KeyError) as exc:diagnostics.append(dict(reason='grounded_proposal_rejected',detail=str(exc),fact=raw))
    if not accepted:return base,diagnostics
    # Concrete literals can fill an omitted class. They cannot vote down the
    # model's explicit type/state for an already covered field, even if a short
    # lexical window has lost the example marker in the next sentence.
    fields={f['field'] for f in accepted}
    extras=[f for f in base if f['field'] in VALUE_FIELDS and f['field'] not in fields]
    if source['role']=='tool':extras+=[f for f in base if f['field']=='other' and f.get('topic')=='execution']
    # Preserve a source-visible preference condition when the model excerpt is
    # only its prefix. Keep its semantic labels and use the larger exact quote.
    for f in accepted:
        if f['field']=='preference':
            candidates=[g for g in base if g['field']=='preference' and f['quote'] in g['quote'] and re.search(r'只有.+才|仅在|只在',g['quote'])]
            if candidates:
                q=min(candidates,key=lambda g:len(g['quote']))['quote'];f.update(quote=q,value_text=q)
    unique={}
    for f in accepted+extras:
        key=(f['kind'],f['epistemic'],f['value_text'])
        unique.setdefault(key,f)
    return list(unique.values()),diagnostics
