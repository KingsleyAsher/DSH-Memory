"""Shared request coverage selection used in runtime and policy calibration."""
from .atoms import frame_compatible
from .reminders import reminder_evidence_strength

def choose_units(ranked,requests,max_units=4):
    chosen=[];seen=set();uncovered=list(requests)
    while uncovered and len(chosen)<max_units:
        options=[]
        for order,row in enumerate(ranked):
            if row['unit_id'] in seen:continue
            hit=[r for r in uncovered if any(frame_compatible(f,r) for f in row['facts'])]
            strength=sum(max((reminder_evidence_strength(f,r) for f in row['facts'] if frame_compatible(f,r)),default=0) for r in hit)
            if hit:options.append((len(hit),strength,float(row['score']),-order,row,hit))
        if not options:break
        _,_,_,_,row,hit=max(options,key=lambda x:x[:4]);chosen.append(row);seen.add(row['unit_id']);ids={r['id'] for r in hit};uncovered=[r for r in uncovered if r['id'] not in ids]
    # An 'any' request has no type-based completeness claim. Preserve one
    # close fallback only in that explicitly uncertain case.
    if any(r['field']=='any' for r in requests) and len(chosen)<max_units:
        backup=next((r for r in ranked if r['unit_id'] not in seen),None)
        if backup and chosen and chosen[0]['score']-backup['score']<=.04:chosen.append(backup)
    return chosen
