"""Project persisted retractions as decisions, never as positive old facts."""
from .identity import event_key
from .views import canonical_event
import re


def withdrawal_request(question,frames):
    """A named withdrawn claim needs its decision, not a nearby live cause."""
    if not re.search('还成立|仍成立|是否成立|还有效|仍有效|还适用|是否撤回|已撤回|现在还|当前还',question):return None
    if re.search('以及|还有|另外|同时|分别|并且|和|与|及|[，,；;]|[？?].+',question):return None
    query=re.sub(r'[\W_]+','',question)
    matched=[]
    for frame in frames:
        if frame.get('operation_action')!='retract' or frame.get('field')!='incident_cause':continue
        for value in frame.get('operation_target_values',[]):
            body=re.sub(r'^(?:我|当时|怀疑|猜测|猜|可能|推测|是|认为|觉得|也)+','',value)
            body=re.sub(r'[\W_]+','',body)
            if len(body)>=4 and body in query:matched.append(frame);break
    if not matched:return None
    keys={(f['field'],canonical_event(f['topic'])) for f in matched}
    if len(keys)!=1:return None
    field,event=next(iter(keys))
    return dict(id='r0',field=field,event=event,mode='status',label=event+'·已撤回说法状态',
                target_claim_ids=sorted({t for f in matched for t in f.get('operation_target_ids',[])}),allowed_evidence_ids=[])


def operation_frames(store, at, project=None, entity=None):
    if not hasattr(store,'operation_records'):
        return []
    frames=[];seen=set()
    active=store.scoped_facts(at,project,entity)
    for operation in store.operation_records(at,project,entity):
        if operation.get('action')!='retract' or operation.get('record_kind') is not None:
            continue
        p,e=operation.get('project'),operation.get('entity')
        scope=store.db.execute('SELECT * FROM scope_keys WHERE project=? AND entity=?',(p,e)).fetchone()
        if not scope:continue
        quote=operation.get('quote','')
        if not quote:continue
        for target in operation.get('targets',[]):
            topic=canonical_event(operation.get('event') or target.get('topic',''))
            # A later reassertion of the same value is a different current
            # version; do not present an older withdrawal as its current state.
            if any(f['seq']>operation['seq'] and f['field']==target['field']
                   and canonical_event(f.get('topic',''))==topic
                   and f['value_text']==target.get('value_text') for f in active):
                continue
            key=(operation['source_id'],target['id'],quote,topic,operation.get('category'),operation.get('property'))
            if key in seen:continue
            seen.add(key)
            proof=[dict(source_id=operation['source_id'],quote=quote)]
            if target.get('source_id') and target.get('quote'):
                proof.append(dict(source_id=target['source_id'],quote=target['quote']))
            eid=operation.get('event_id') or event_key(scope['entity_id'],topic,target.get('kind','fact'))
            category=operation.get('category') or target.get('category','event')
            frame=dict(id='operation:'+operation['source_id']+':'+str(operation.get('op_index',0))+':'+target['id'],
                source_id=operation['source_id'],seq=operation['seq'],project=p,entity=e,
                project_id=scope['project_id'],entity_id=scope['entity_id'],event_id=eid,
                field=target['field'],topic=topic,kind=target.get('kind','fact'),epistemic='unknown',
                value=quote,value_text=quote,quote=quote,valid_to=None,superseded_by=None,
                record_kind='operation',category=category,property=operation.get('property','value'),
                attribute=target.get('attribute',target['field']),operation_action='retract',
                operation_target_values=[target.get('value_text','')],operation_target_ids=[target['id']],
                evidence=proof,source_ids=list(dict.fromkeys([operation['source_id'],*operation.get('proof_sources',[])])))
            if category=='reminder':frame['reminder_event']=True
            frames.append(frame)
    return frames
