"""Stable source scope keys and explicit reference resolution, never fuzzy ACLs."""
import re
from .contract import sha

def project_key(label):return 'p:'+sha(label)[:24]
def entity_key(project_id,label):return 'e:'+sha(project_id+'\0'+label)[:24]
def event_key(entity_id,label,kind='fact'):return 'v:'+sha(entity_id+'\0'+kind+'\0'+label)[:24]

def scope_pattern(project,entity):return re.escape(project)+r'(?:项目)?(?:这边|那边|这里)?(?:的|中(?:的)?|里(?:的)?)?'+re.escape(entity)

def query_text(question,project,entity,event=None):
    task=re.sub(r'^(?:在)?'+scope_pattern(project,entity)+r'[，,\s]*','',question)
    query=project+'的'+entity+'，'+task
    if event:query+='；所指事件为'+event
    return task,query

def resolve_scope(question,registry,context=None):
    context=context or {};scopes=registry.get('scopes',[])
    pairs=[]
    for p in registry['projects']:
        for e in registry['entities']:
            pattern=scope_pattern(p,e)
            if re.search(pattern,question):pairs.append((p,e))
            elif re.search(re.escape(p)+r'项目[^，,；;。]{0,20}'+re.escape(e),question):pairs.append((p,e))
    pairs=list(dict.fromkeys(pairs))
    # The caller's stable IDs are scope, not model-authored labels.
    pid=context.get('project_id');eid=context.get('entity_id')
    if pid or eid:
        rows=[s for s in scopes if (not pid or s['project_id']==pid) and (not eid or s['entity_id']==eid)]
        names={(s['project'],s['entity']) for s in rows}
        if len(names)!=1:return None,None,'unknown_scope_id'
        pair=next(iter(names))
        if pairs and set(pairs)!={pair}:return None,None,'scope_context_conflict'
        return *pair,'stable_ids'
    if len(pairs)==1:return *pairs[0],'explicit_pair'
    if len(pairs)>1:return None,None,'multiple_explicit_scopes'
    p=context.get('project');e=context.get('entity')
    if p in registry['projects'] and e in registry['entities']:
        if scopes and not any(s['project']==p and s['entity']==e for s in scopes):return None,None,'unknown_scope_pair'
        return p,e,'declared_context'
    # Backwards-compatible unambiguous names, restricted to reference position.
    ps=[p for p in registry['projects'] if re.search(r'(?:^|[，,；;。\s])'+re.escape(p)+r'(?:项目|的|[，,；;。])',question)]
    es=[e for e in registry['entities'] if e in question]
    if len(ps)==len(es)==1:return ps[0],es[0],'explicit_names'
    return None,None,'scope_ambiguous'
