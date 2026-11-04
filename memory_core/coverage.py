"""Budgeted source groups cover query requests before adding redundant facts."""
from .atoms import frame_compatible

def covered_requests(facts,requests):
    return [r['id'] for r in requests if any(frame_compatible(f,r) for f in facts)]

def pack(facts,requests,make_item,counter,budget):
    groups={}
    for f in facts:groups.setdefault((f['source_id'],f['field'],f.get('topic',''),f['kind']),[]).append(f)
    selected=[];packet=[];remaining=list(groups.values());covered=set()
    while remaining:
        options=[]
        for order,group in enumerate(remaining):
            fresh=[f for f in group if f['id'] not in {s['id'] for s in selected}]
            items=[make_item(f,len(packet)+i+1) for i,f in enumerate(fresh)]
            if not fresh or counter(packet+items)>budget:continue
            hits=set(covered_requests(fresh,requests));gain=len(hits-covered)
            # Once all requests have a frame, retain complementary facts in
            # already requested groups, not unrelated score-ranked padding.
            if not hits:continue
            cost=counter(items)
            options.append((gain,not any(f.get('control') for f in fresh),-order,-cost,group,fresh,items,hits))
        if not options:break
        choice=max(options,key=lambda x:x[:4]);group,fresh,items,hits=choice[4:]
        if covered and choice[0]==0 and len(covered)<len(requests):break
        selected.extend(fresh);packet.extend(items);covered|=hits;remaining.remove(group)
    return selected,packet,dict(covered=sorted(covered),missing=[r['id'] for r in requests if r['id'] not in covered],memory_tokens=counter(packet) if packet else 0,budget=budget)
