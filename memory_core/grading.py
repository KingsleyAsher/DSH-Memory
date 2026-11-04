"""Independent event/argument/value/citation scoring, with visible atom traces.

Gold is used only by this evaluator, never runtime. Predicates remain bounded
and disclosed; this is not a general semantic entailment proof.
"""
import re
from .atoms import segment_answer,confirmed,clocks,value_present,literal_tokens,REFUSAL,UNKNOWN,HYPOTHESIS,compact
from .views import canonical_event
from .policy import FIELD_LABELS
from .semantics import canonical,strip_presentation,deployment_parent,pattern_matches

def _event(g):return canonical_event(g.get('event',g.get('event_key',g.get('topic','')) ) or '')
def source_support(f,g,source_catalog=None):
    if f.get('control') and g.get('value') is not None:return False
    allowed=g.get('source_ids',[g.get('source_id')])
    if source_catalog is None or g.get('strict_source'):
        if f['source_id'] not in allowed:return False
    else:
        source=source_catalog.get(f['source_id'])
        if not source or source.get('role') not in ['user','tool'] or f['quote'] not in source['text'] or f['value_text'] not in f['quote']:return False
        if any(g.get(k) is not None and source.get(k)!=g[k] for k in ['project','entity']):return False
        if any(f.get(k) is not None and source.get(k)!=f[k] for k in ['project','entity']):return False
    observation=(g['field']=='other' and source_catalog is not None and source_catalog.get(f['source_id'],{}).get('role')=='tool' and bool(re.search(r'退出码|错误|返回|没有生成|没有产生',f['quote'])))
    if f['field']!=g['field'] and not f.get('control') and not observation:return False
    if g.get('kind') and f['kind']!=g['kind']:return False
    if _event(g) and canonical_event(f.get('topic',f.get('event_key','')))!=_event(g):
        if not (g['field']=='deployment_state' and source_catalog and deployment_parent(source_catalog.get(f['source_id'],{}).get('text',''),f.get('topic',''),_event(g))):return False
    if g.get('status') and f['epistemic'] not in g['status']:return False
    text=f['value_text']+' '+f['quote']+' '+f.get('value','')
    if g.get('value') is not None:return value_present(g['field'],g['value'],text)
    return all(any(pattern_matches(p,text) for p in group) for group in g.get('answer_groups',[]))
def components(g):
    return [{**g,'answer_groups':[part]} for part in g.get('answer_groups',[])] if g.get('value') is None and g.get('answer_groups') else [g]

def evidence_coverage(requirements,delivered,source_catalog=None):
    hits=[any(all(any(source_support(f,c,source_catalog) for f in delivered) for c in components(g)) for g in group) for group in requirements]
    return dict(complete=bool(hits) and all(hits),hit=sum(hits),total=len(hits),groups=hits)
def _meaning(segment,g):
    text=segment['text'];event=_event(g)
    if event and segment.get('event')!=event:return False
    if g['field']=='incident_solution' and re.search(r'下次|今后|以后',text) and not re.search(r'已经|已执行|后来|后.*(?:通过|正常|恢复)',text):return False
    if g['field']=='incident_rule' and segment.get('field')=='incident_solution' and not re.search(r'下次|以后|今后|必须|不能',text):return False
    if g.get('value') is not None:return value_present(g['field'],g['value'],text)
    if g.get('status') and any(s in ['unknown','hypothesis'] for s in g['status']) and confirmed(text):return False
    groups=g.get('answer_groups',[])
    semantic_text=text
    if g.get('status') and 'unknown' in g['status'] and re.search(UNKNOWN,text) and not confirmed(text):semantic_text+=' 未知'
    return bool(groups) and all(any(pattern_matches(p,semantic_text) for p in group) for group in groups)
def score(response,label,claimmap,delivered,source_catalog=None):
    value=response.get('value') if isinstance(response,dict) else None
    if not isinstance(value,dict) or set(value)!={'answerable','answer','source_ids'} or not isinstance(value.get('answer'),str) or not isinstance(value.get('answerable'),bool) or not isinstance(value.get('source_ids'),list):
        return dict(correct=False,content_correct=False,protocol_correct=False,citation_correct=False,reason='invalid_public_schema',required_hits=0,required_total=0,atoms=[])
    text=value['answer'].strip();citations=value['source_ids'];allowed={f['source_id'] for f in delivered};invalid=any(not isinstance(s,str) or s not in allowed for s in citations)
    scoring_text=strip_presentation(text,citations)
    groups=label.get('target_groups') or ([label['targets']] if label.get('targets') else [])
    requirements=[[{**claimmap[mid],**({'strict_source':True} if label.get('category')=='history' else {})} for mid in group] for group in groups]
    relevant=[g for group in requirements for g in group]
    truth_ids=label.get('truth_ids') or list(claimmap)
    truth=[claimmap[mid] for mid in truth_ids if mid in claimmap]
    names={_event(g) for g in truth if _event(g)}
    asked={_event(g) for g in relevant if _event(g)}
    negative_events={canonical_event(e) for e in label.get('events',[])}
    default=next(iter(asked)) if len(asked)==1 else next(iter(negative_events)) if len(negative_events)==1 else None
    trace=response.get('assertions') or []
    atoms=[]
    if trace:
        # Metadata is not trusted as content: split explicit cross-event text
        # again, then compare each segment with independent expected frames.
        by_id={f['id']:f for f in delivered}
        for a in trace:
            segments=segment_answer(a['text'],names,canonical_event(a.get('event','')) or default)
            for seg in segments:
                ids=a.get('fact_ids',[]);facts=[by_id[i] for i in ids if i in by_id]
                atoms.append({**seg,'facts':facts,'source_ids':a.get('source_ids',[]),'claimed_field':a.get('field'),'trace_resolution':a.get('resolution')})
    else:
        for seg in segment_answer(scoring_text,names,default):atoms.append({**seg,'facts':[f for f in delivered if f['source_id'] in citations],'source_ids':citations,'claimed_field':None})
    # The public text and trace must describe the same answer. Metadata cannot
    # hide an extra unsupported assertion in the public body.
    trace_ok=True
    if trace:
        residue=text
        for a in trace:
            if compact(a['text']) not in compact(text):trace_ok=False
            residue=residue.replace(a['text'],'',1)
        for a in trace:
            title=(a.get('event','')+'·' if a.get('event') else '')+FIELD_LABELS.get(a.get('field'),'所问内容')
            residue=residue.replace(title+'：','')
        residue=re.sub(r'所问凭据：|所问内容：|执行观测：|邮箱：','',residue)
        if compact(residue):trace_ok=False
    group_hits=[]
    for group in requirements:
        def covered(g):
            compatible=[a for a in atoms if not _event(g) or a['event']==_event(g)]
            hits=all(any(_meaning(a,c) and any(f['source_id'] in a['source_ids'] and source_support(f,c,source_catalog) for f in a['facts']) for a in compatible) for c in components(g))
            # Preserve a conditional preference's relation, not just its nouns.
            if hits and g['field']=='preference':
                quotes=' '.join(f['quote'] for a in compatible for f in a['facts'] if source_support(f,g,source_catalog))
                if re.search(r'只有.+才|仅在|只在',quotes):hits=bool(re.search(r'只有.+才|仅在|只在|才(?:补|附|加|展)', '；'.join(a['text'] for a in compatible)))
            return hits
        group_hits.append(any(covered(g) for g in group))
    grounding=[];unused_cites=set(citations)
    def valid_extra(f):
        # Gold need not enumerate every sentence of a valid current source.
        # Only a known-current same source/frame can support an extra verbatim
        # statement. This does not satisfy a missing requested predicate.
        if not source_catalog:return False
        s=source_catalog.get(f['source_id'],{})
        if s.get('role') not in ['user','tool'] or f['quote'] not in s.get('text','') or f['value_text'] not in f['quote']:return False
        return any(f['source_id'] in g.get('source_ids',[g.get('source_id')]) and (f['field']==g['field'] or f['field'].startswith('incident_') and g['field'].startswith('incident_')) and f['kind']==g.get('kind',f['kind']) and (canonical_event(f.get('topic',''))==_event(g) or f['field']=='other' and f.get('topic')=='execution' and not _event(g)) for g in truth)
    for a in atoms:
        matches=[c for g in truth for c in components(g) if _meaning(a,c)]
        supporting=[f for f in a['facts'] if f['source_id'] in a['source_ids'] and any(source_support(f,g,source_catalog) for g in matches)]
        empty_refusal=bool(re.search(REFUSAL,a['text'])) and not confirmed(a['text'])
        controls=[f for f in a['facts'] if f.get('control') and f['source_id'] in a['source_ids'] and (source_catalog is None or (source_catalog.get(f['source_id'],{}).get('role') in ['user','tool'] and f['quote'] in source_catalog[f['source_id']]['text']))]
        control_state=bool(controls) and a.get('claimed_field') in {f['field'] for f in controls} and a.get('trace_resolution')=='unavailable' and not literal_tokens(a['text']) and not confirmed(a['text']) and bool(re.search(REFUSAL+'|冲突|未核实|未核对',a['text']))
        if control_state:
            good=True
            for f in controls:unused_cites.discard(f['source_id'])
        elif supporting:
            good=True
            for f in supporting:unused_cites.discard(f['source_id'])
        elif any(
            (valid_extra(f) or any(source_support(f,c,source_catalog) for g in truth for c in components(g)))
            and any(canonical(a['text']) in canonical(s['text']) and (a['event']==s['event'] or not a['event'] and (not s['event'] or f['field']=='other' and f.get('topic')=='execution')) for s in segment_answer(f['quote'],names,canonical_event(f.get('topic','')) or None))
            for f in a['facts'] if f['source_id'] in a['source_ids']
        ):
            # Extra verbatim statements can be grounded even when the gold
            # lists only the requested attributes of this same valid frame.
            # This never satisfies a missing required slot or changes event
            # binding: source-sentence context must still agree.
            good=True
            for f in a['facts']:
                if valid_extra(f) or any(source_support(f,c,source_catalog) for g in truth for c in components(g)):unused_cites.discard(f['source_id'])
        elif not label['abstain'] and all(group_hits) and re.fullmatch(r'(?:两项|各项|上述各项|这两项)(?:均|都)(?:有明确记录|有记录|可确认)(?:，可确认)?',a['text']):
            good=True  # A summary of already proven slots adds no new fact.
        elif source_catalog and compact(a['text']) in {compact(s['project']+'的'+s['entity']) for s in source_catalog.values()}:
            good=True  # An isolated scope heading is not a world assertion.
        elif label['abstain'] and empty_refusal:
            # Absence can be stated without inventing a source. If citations are
            # attached, they must be expected refusal/control support.
            support_ids=set(label.get('refusal_source_ids',[]))
            good=not trace or not a['source_ids'] or set(a['source_ids'])<=support_ids
            if set(a['source_ids'])<=support_ids:unused_cites-=set(a['source_ids'])
        else:
            # Short connective headings are not asserted world facts.
            good=not re.search(r'[\u4e00-\u9fffA-Za-z0-9]{3}',a['text'])
        a['grounded']=good;grounding.append(good)
    if label['abstain']:
        # Only confirmation attached to the requested event can contradict a
        # refusal; a different event's known cause does not upgrade this one.
        target_events={canonical_event(e) for e in label.get('events',[])}
        bad_confirm=any(confirmed(a['text']) and (not target_events or a['event'] in target_events) for a in atoms)
        refusal=bool(re.search(REFUSAL,text))
        content=refusal and not bad_confirm and all(grounding)
    else:content=bool(group_hits) and all(group_hits) and all(grounding)
    # Public protocol is judged independently; unlike the old grader, a false
    # answerable flag is not forgiven just because text happens to refuse.
    protocol=value['answerable']==(not label['abstain'])
    citation=not invalid and not unused_cites and all(grounding)
    correct=bool(text) and content and protocol and citation and trace_ok
    reason='grounded_event_assertions' if correct else 'content_or_binding_missing' if not content else 'protocol_mismatch' if not protocol else 'citation_mismatch'
    return dict(correct=correct,content_correct=content,protocol_correct=protocol,citation_correct=citation,trace_consistent=trace_ok,reason=reason if trace_ok else 'public_trace_mismatch',required_hits=sum(group_hits),required_total=len(group_hits),assertions_grounded=sum(grounding),assertions_total=len(grounding),unused_citations=sorted(unused_cites),atoms=[{k:v for k,v in a.items() if k!='facts'} for a in atoms])
