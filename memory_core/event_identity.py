"""Explicit semantic operations; code owns identity, versions and provenance.

The language producer chooses what an utterance means. This module never uses
positive mutation keywords as an alternative semantic classifier.
"""
import copy
import json

from .contract import normalize, sha, validate_fact
from .contextual import validate_point
from .identity import event_key
from .policy import SCOPED_FIELDS, VALUE_FIELDS
from .reminders import is_event_reminder, reminder_axis
from .views import canonical_event


OP_KEYS={'action','record_kind','ordinal','target_ids','quote','event','aliases','category','property'}
CATEGORIES={'reminder','event','other'}
PROPERTIES={'schedule','repeat','execution','value'}


class OperationLedger:
    def _init_operation_ledger(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS claim_semantics(
          claim_id TEXT PRIMARY KEY,event_key TEXT NOT NULL,category TEXT NOT NULL,
          property TEXT NOT NULL,proof_sources TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS claim_operation_audit(
          source_id TEXT NOT NULL,op_index INTEGER NOT NULL,detail TEXT NOT NULL,
          PRIMARY KEY(source_id,op_index));
        CREATE TABLE IF NOT EXISTS event_alias_proofs(
          claim_id TEXT NOT NULL,alias TEXT NOT NULL,canonical TEXT NOT NULL,event_id TEXT NOT NULL,
          project TEXT NOT NULL,entity TEXT NOT NULL,kind TEXT NOT NULL,category TEXT NOT NULL,
          proof_sources TEXT NOT NULL,PRIMARY KEY(claim_id,alias));
        CREATE TABLE IF NOT EXISTS pending_operation_changes(
          source_id TEXT NOT NULL,seq INTEGER NOT NULL,target_id TEXT NOT NULL,
          PRIMARY KEY(source_id,target_id));
        ''')

    def _operation_proof_visible(self, sources, at):
        for sid in sources:
            row=self.db.execute('SELECT seq FROM inbox WHERE id=?',(sid,)).fetchone()
            if not row or row['seq']>at or not self.visible_source(sid,at):
                return False
        return True

    def _decorate_operation_claim(self, record, at):
        meta=self.db.execute('SELECT * FROM claim_semantics WHERE claim_id=?',(record['id'],)).fetchone()
        if not meta:
            return record
        if not self._operation_proof_visible(json.loads(meta['proof_sources']),at):
            return None
        record={**record,'topic':meta['event_key'],'category':meta['category'],'property':meta['property']}
        scope=self.register_scope(record['project'],record['entity'])
        record.update(project_id=scope['project_id'],entity_id=scope['entity_id'],
                      event_id=event_key(scope['entity_id'],meta['event_key'],record['kind']) if meta['event_key'] else '')
        if meta['category']=='reminder':
            record['reminder_event']=True
            if record['epistemic']=='unknown':record['control']=True
        return record

    def claim_aliases(self, at=10**12, project=None, entity=None):
        """Only live, proven and unambiguous aliases in the requested scope."""
        rows=self.db.execute('''SELECT a.*,m.valid_to,s.seq FROM event_alias_proofs a
            JOIN memory_claims m ON m.id=a.claim_id JOIN sources s ON s.id=m.source_id
            WHERE s.seq<=? AND (m.valid_to IS NULL OR m.valid_to>?)
            AND (? IS NULL OR a.project=?) AND (? IS NULL OR a.entity=?)''',
            (at,at,project,project,entity,entity)).fetchall()
        proven=[]
        for row in rows:
            if self._operation_proof_visible(json.loads(row['proof_sources']),at):proven.append(dict(row))
        meanings={}
        for row in proven:
            meanings.setdefault((row['project'],row['entity'],row['kind'],row['alias']),set()).add(row['event_id'])
        out={}
        for row in proven:
            if len(meanings[(row['project'],row['entity'],row['kind'],row['alias'])])!=1:continue
            value={k:row[k] for k in ['canonical','alias','event_id','category','kind']}
            out[(row['project'],row['entity'],row['alias'],row['event_id'])]=value
        return list(out.values())

    def operation_records(self, at=10**12, project=None, entity=None):
        rows=self.db.execute('''SELECT a.op_index,a.detail,s.seq,s.project,s.entity FROM claim_operation_audit a
            JOIN sources s ON s.id=a.source_id WHERE s.seq<=?
            AND (? IS NULL OR s.project=?) AND (? IS NULL OR s.entity=?)
            ORDER BY s.seq,a.op_index''',(at,project,project,entity,entity)).fetchall()
        return [{**json.loads(r['detail']),'op_index':r['op_index'],'seq':r['seq'],'project':r['project'],'entity':r['entity']}
                for r in rows if self._operation_proof_visible(json.loads(r['detail'])['proof_sources'],at)]

    def mark_operation_pending(self, source, target_ids):
        if source.get('role')!='user' or not isinstance(target_ids,list):raise ValueError('operation_pending_shape')
        live={r['id'] for r in self.claim_catalog(source)}
        if len(target_ids)>8 or len(set(target_ids))!=len(target_ids) or not set(target_ids)<=live:
            raise ValueError('operation_pending_target')
        with self.db:
            for cid in target_ids:self.db.execute('INSERT OR IGNORE INTO pending_operation_changes VALUES(?,?,?)',(source['id'],source['seq'],cid))
            if target_ids:self.bump()

    def _operation_semantics(self, target):
        meta=self.db.execute('SELECT * FROM claim_semantics WHERE claim_id=?',(target['id'],)).fetchone()
        if meta:
            return dict(event=meta['event_key'],category=meta['category'],property=meta['property'],
                        proofs=json.loads(meta['proof_sources']))
        reminder=is_event_reminder(target,target.get('attribute',''))
        prop=reminder_axis(target,target.get('attribute','')) if reminder else 'value'
        return dict(event=target.get('topic',''),category='reminder' if reminder else 'other',
                    property=prop,proofs=[target['source_id']])

    @staticmethod
    def _operation_shape(op, source):
        if not isinstance(op,dict) or set(op)!=OP_KEYS:raise ValueError('mutation_operation_shape')
        action=op['action'];rk=op['record_kind'];ordinal=op['ordinal'];targets=op['target_ids']
        if action not in {'assert','replace','retract','retain'}:raise ValueError('mutation_operation_action')
        if rk is None:
            if ordinal is not None or action in {'assert','replace'}:raise ValueError('mutation_operation_record')
        elif rk not in {'fact','linked'} or type(ordinal) is not int or ordinal<0:
            raise ValueError('mutation_operation_record')
        if (not isinstance(targets,list) or len(targets)>4 or len(set(targets))!=len(targets)
                or any(not isinstance(t,str) or not t for t in targets)):
            raise ValueError('mutation_operation_targets')
        if (action=='assert' and targets) or (action!='assert' and not targets):raise ValueError('mutation_operation_target_coverage')
        if source['role']!='user' and action!='assert':raise ValueError('mutation_operation_role')
        if (not isinstance(op['quote'],str) or not op['quote'] or len(op['quote'])>2400
                or op['quote'] not in source['text']):raise ValueError('mutation_operation_quote')
        if (not isinstance(op['event'],str) or len(op['event'])>80 or op['event']!=op['event'].strip()
                or op['category'] not in CATEGORIES or op['property'] not in PROPERTIES):
            raise ValueError('mutation_operation_identity')
        aliases=op['aliases']
        if (not isinstance(aliases,list) or len(aliases)>4 or len(set(aliases))!=len(aliases)
                or any(not isinstance(a,str) or not a.strip() or len(a)>80 or a!=a.strip() for a in aliases)):
            raise ValueError('mutation_operation_aliases')

    def _finish_operations(self, source, result, linked_context=None, *, append=False, _on_commit=None, _partial=False):
        source,result=copy.deepcopy(source),copy.deepcopy(result)
        if type(result.get('mutation_contract')) is not int or result['mutation_contract']!=1:
            raise ValueError('mutation_contract_version')
        inbox=self.db.execute('SELECT * FROM inbox WHERE id=?',(source['id'],)).fetchone()
        if not inbox or inbox['state']=='deleted' or inbox['sha']!=sha(source['text']):raise ValueError('source_unavailable_or_changed')
        saved=json.loads(inbox['payload'])
        if any(saved.get(k)!=source.get(k) for k in ['id','seq','project','entity','role','text']):raise ValueError('source_identity_changed')
        if not self.visible_source(source['id']):raise ValueError('source_not_visible')
        old=self.db.execute('SELECT sha,state,proposal FROM sources WHERE id=?',(source['id'],)).fetchone()
        if old:
            if old['sha']!=sha(source['text']):raise ValueError('source_id_changed')
            if not append:return old['state']
        previous=json.loads(old['proposal'] or '{}') if old else {}
        if append and old:
            # Appending never rewrites an earlier claim or reuses its ordinal.
            for key,kind in [('claim_specs','fact'),('linked_specs','linked')]:
                used={r[0] for r in self.db.execute('SELECT ordinal FROM memory_claims WHERE source_id=? AND record_kind=?',(source['id'],kind))}
                if used & {s['ordinal'] for s in result.get(key,[])}:raise ValueError('append_ordinal_collision')
        op_offset=self.db.execute('SELECT COALESCE(MAX(op_index),-1)+1 FROM claim_operation_audit WHERE source_id=?',(source['id'],)).fetchone()[0] if old else 0
        facts,specs=result.get('facts',[]),result.get('claim_specs',[])
        points,pspecs=result.get('linked_points',[]),result.get('linked_specs',[])
        self._validate_specs(facts,specs);self._validate_specs(points,pspecs)
        if len(facts)>16 or len(points)>4:raise ValueError('mutation_record_budget')
        if result.get('diagnostics') or result.get('retract_claims'):raise ValueError('mutation_mixed_or_invalid_proposal')
        records={}
        for rk,values,metas in [('fact',facts,specs),('linked',points,pspecs)]:
            for record,spec in zip(values,metas):
                if spec['replace_ids']:raise ValueError('mutation_implicit_replace_forbidden')
                if rk=='fact':
                    validate_fact(source['text'],record)
                    if source['role'] not in ['user','tool']:raise ValueError('assistant_not_long_term_fact')
                    if source['role']=='tool':
                        from .atomic_wire import tool_evidence_boundary
                        if record['field'].startswith('incident_') and not tool_evidence_boundary(record,dict(lifetime=spec['lifetime'],replace_refs=[])):
                            raise ValueError('tool_cannot_assert_business_cause')
                        if record['field']=='preference':raise ValueError('tool_cannot_set_user_policy')
                else:
                    if source['role']!='user':raise ValueError('linked_confirmation_required')
                    context=[]
                    for ref in linked_context if linked_context is not None else self.recent_dialogue(source):
                        raw=self._raw_claim_evidence(ref['id'])
                        row=self.db.execute('SELECT session_id FROM inbox WHERE id=?',(ref['id'],)).fetchone()
                        if raw and row and row['session_id']==saved.get('session_id','default'):context.append(raw)
                    validate_point(record,source,context)
                records[(rk,spec['ordinal'])]=(record,spec)
        ops=result.get('mutation_ops')
        if not isinstance(ops,list) or len(ops)>32:raise ValueError('mutation_operations_budget')
        by_record={}
        for op in ops:
            self._operation_shape(op,source)
            if op['record_kind'] is not None:
                key=(op['record_kind'],op['ordinal'])
                if key not in records or key in by_record:raise ValueError('mutation_record_coverage')
                by_record[key]=op
                record=records[key][0]
                current=record.get('quote') if key[0]=='fact' else next((e['quote'] for e in record['evidence'] if e['source_id']==source['id']),None)
                if current not in op['quote'] and op['quote'] not in current:raise ValueError('mutation_record_evidence')
        if set(by_record)!=set(records):raise ValueError('mutation_record_coverage')
        diagnostics=[]
        actions=self._validated_actions(source,result,diagnostics) if source['role'] in {'user','tool'} else {}
        if diagnostics:raise ValueError('mutation_action_provenance')
        if source['role']!='user' and any(v in {'set','pending'} for v in actions.values()):raise ValueError('mutation_configuration_role')
        for record,_ in records.values():
            if record.get('kind')=='fact' and actions.get(record.get('field'))=='pending' and normalize(record['field'],record['value_text'])!='__unset__':
                raise ValueError('pending_value_not_current')
        with self.db:
            catalog={r['id']:r for r in self.claim_catalog(source)}
            scalar_fields={r['field'] for r,_ in records.values() if r.get('kind')=='fact' and r.get('field') in VALUE_FIELDS and r.get('epistemic')!='planned'}
            scalar_fields.update(k for k,v in actions.items() if v in {'set','pending'})
            if scalar_fields:
                later=self.db.execute('''SELECT DISTINCT f.field,f.source_id FROM facts f
                    WHERE f.project=? AND f.entity=? AND f.seq>?''',(source['project'],source['entity'],source['seq'])).fetchall()
                if any(r['field'] in scalar_fields and self.visible_source(r['source_id']) for r in later):
                    raise ValueError('late_mutation_requires_review')
            resolved=[];mutated=set()
            for index,op in enumerate(ops):
                targets=[]
                for cid in op['target_ids']:
                    target=catalog.get(cid)
                    if not target:raise ValueError('mutation_target_not_live_before_source:'+cid)
                    if cid in mutated and op['action'] in {'replace','retract'}:raise ValueError('mutation_target_twice')
                    targets.append(target)
                pair=records.get((op['record_kind'],op['ordinal']))
                record,spec=pair if pair else (None,None)
                field=record.get('field','other') if record else targets[0]['field']
                kind=record.get('kind','fact') if record else targets[0]['kind']
                event=canonical_event(op['event'] or (record.get('topic','') if record else ''))
                category,prop=op['category'],op['property']
                if source['role']=='tool' and category=='reminder' and prop!='execution':
                    raise ValueError('tool_cannot_author_reminder_arrangement')
                proofs={source['id']}
                if op['record_kind']=='linked':proofs.update(e['source_id'] for e in record['evidence'])
                inherited=set()
                if targets:
                    canonical=targets[0];sem=self._operation_semantics(canonical)
                    for target in targets:
                        tsem=self._operation_semantics(target)
                        if target['field']!=field or target['kind']!=kind:raise ValueError('mutation_target_frame_mismatch')
                        if (tsem['event'],tsem['category'],tsem['property'])!=(sem['event'],sem['category'],sem['property']):
                            raise ValueError('mutation_target_identity_mismatch')
                        if op['action']=='replace' and target['slot']!=canonical['slot']:raise ValueError('mutation_target_slot_mismatch')
                        if (sem['category']=='reminder' or self.db.execute('SELECT 1 FROM claim_semantics WHERE claim_id=?',(target['id'],)).fetchone()) and (category!=sem['category'] or prop!=sem['property']):
                            raise ValueError('mutation_target_property_mismatch')
                        later=self.db.execute('''SELECT m.id,s.id source_id FROM memory_claims m JOIN sources s ON s.id=m.source_id
                            WHERE m.slot=? AND s.seq>?''',(target['slot'],source['seq'])).fetchall()
                        if (op['action'] in {'replace','retract'} or record is not None) and any(self.visible_source(r['source_id']) for r in later):
                            raise ValueError('late_mutation_requires_review')
                        proofs.update(tsem['proofs']);proofs.add(target['source_id'])
                        inherited.update(r['alias'] for r in self.db.execute('SELECT alias FROM event_alias_proofs WHERE claim_id=?',(target['id'],)))
                        if target.get('topic'):inherited.add(target['topic'])
                    event=sem['event'];category=sem['category'] if sem['category']=='reminder' else category
                    if spec:spec['attribute']=canonical['attribute']
                if category in {'reminder','event'} and not event:raise ValueError('mutation_event_required')
                if field in VALUE_FIELDS:
                    if category!='other' or prop!='value':raise ValueError('mutation_scalar_identity')
                    if record and record['epistemic']=='planned' and op['action'] in {'replace','retract'}:
                        raise ValueError('planned_scalar_not_current_mutation')
                    event=''
                if record and op['record_kind']=='fact':record['topic']=event
                if op['action']=='assert' and category=='reminder' and prop=='schedule':
                    later=self.db.execute('''SELECT m.source_id FROM claim_semantics x JOIN memory_claims m ON m.id=x.claim_id
                        JOIN sources s ON s.id=m.source_id WHERE s.project=? AND s.entity=? AND s.seq>?
                        AND x.event_key=? AND x.category='reminder' AND x.property='schedule' ''',
                        (source['project'],source['entity'],source['seq'],event)).fetchall()
                    if any(self.visible_source(r['source_id']) for r in later):raise ValueError('late_mutation_requires_review')
                # New typed slots separate purpose properties even when the
                # producer reuses a human attribute label. An explicit update
                # preserves its actual predecessor's slot, including legacy IDs.
                slot=targets[0]['slot'] if targets and spec else json.dumps([source['project'],source['entity'],kind,field,event,spec['attribute'],category,prop],ensure_ascii=False,separators=(',',':')) if spec else None
                if spec and op['action']=='assert' and (field in VALUE_FIELDS and record['epistemic']!='planned' or category=='reminder' and prop=='schedule'):
                    if any(t['field']==field and t['kind']==kind and self._operation_semantics(t)['event']==event
                           and (field not in VALUE_FIELDS or t['epistemic']!='planned')
                           and (field in VALUE_FIELDS or self._operation_semantics(t)['property']=='schedule') for t in catalog.values()):
                        raise ValueError('assert_existing_single_value_requires_operation')
                cid=sha(source['id']+(':claim:' if op['record_kind']=='fact' else ':link:')+str(op['ordinal']))[:20] if record else None
                resolved.append((index,op,record,spec,cid,targets,field,kind,event,category,prop,sorted(proofs),inherited,slot))
                if op['action'] in {'replace','retract'}:mutated.update(op['target_ids'])
            required={r['target_id'] for r in self.db.execute('SELECT target_id FROM pending_operation_changes WHERE source_id=?',(source['id'],))}
            required.update(r['target_id'] for r in self.db.execute('SELECT target_id FROM pending_claim_changes WHERE source_id=?',(source['id'],)))
            required.update(r['target_id'] for r in self._pending_reminder_rows(source['seq'],source['id']))
            handled={cid for op in ops for cid in op['target_ids']}
            if required-handled and not _partial:raise ValueError('unresolved_operation_target')
            for field,action in actions.items():
                if action=='set':
                    old_ids={t['id'] for t in catalog.values() if t['field']==field and t['kind']=='fact' and t['epistemic']!='planned'}
                    if old_ids-mutated:raise ValueError('unresolved_scalar_update')
            proposal={**result,'diagnostics':[],'semantic_actions':actions,'pending_fields':sorted(k for k,v in actions.items() if v=='pending')}
            if old:
                for key in ['facts','claim_specs','linked_points','linked_specs','session_points','mutation_ops']:
                    proposal[key]=previous.get(key,[])+proposal.get(key,[])
                proposal['semantic_actions']={**previous.get('semantic_actions',{}),**actions}
                self.db.execute('UPDATE sources SET proposal=? WHERE id=?',(json.dumps(proposal,ensure_ascii=False),source['id']))
            else:
                self.db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',(source['id'],source['seq'],source['project'],source['entity'],source['role'],source['text'],sha(source['text']),'accepted',None,json.dumps(proposal,ensure_ascii=False)))
            if not _partial:self.db.execute('DELETE FROM pending_updates WHERE source_id=?',(source['id'],))
            self.db.execute('INSERT OR REPLACE INTO source_reviews VALUES(?,?,?)',(source['id'],json.dumps(actions),json.dumps(result.get('semantic_review',{}),ensure_ascii=False)))
            for field,action in actions.items():
                if action=='pending':self.db.execute('INSERT INTO pending_updates VALUES(?,?,?,?,?,NULL)',(source['id'],source['seq'],source['project'],source['entity'],field))
            for index,op,record,spec,cid,targets,field,kind,event,category,prop,proofs,inherited,slot in resolved:
                if record:
                    if op['record_kind']=='fact':
                        self.db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,source['id'],source['seq'],source['project'],source['entity'],field,event,kind,record['epistemic'],normalize(field,record['value_text']),record['value_text'],record['quote'],None,None))
                    self.db.execute('INSERT INTO memory_claims VALUES(?,?,?,?,?,?,?,NULL,NULL)',(cid,source['id'],spec['ordinal'],op['record_kind'],spec['attribute'],spec['lifetime'],slot))
                    self.db.execute('INSERT INTO claim_semantics VALUES(?,?,?,?,?)',(cid,event,category,prop,json.dumps(proofs)))
                    scope=self.register_scope(source['project'],source['entity'])
                    eid=event_key(scope['entity_id'],event,kind) if event else ''
                    aliases=inherited|set(op['aliases'])|{event,op['event']}
                    for alias in sorted(a for a in aliases if a):
                        self.db.execute('INSERT OR IGNORE INTO event_alias_proofs VALUES(?,?,?,?,?,?,?,?,?)',(cid,alias,event,eid,source['project'],source['entity'],kind,category,json.dumps(proofs)))
                    if event:self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)',(source['project'],source['entity'],kind,event,event))
                if op['action'] in {'replace','retract'}:
                    for target in targets:self._invalidate_claim(target['id'],source['seq'],cid or 'retract:'+source['id'])
                if op['action']=='retain' and not record and targets:
                    # A retain adds evidence-backed aliases without changing the
                    # target claim's lifetime or claiming execution success.
                    scope=self.register_scope(source['project'],source['entity'])
                    for alias in set(op['aliases'])|{op['event']}:
                        if alias:self.db.execute('INSERT OR IGNORE INTO event_alias_proofs VALUES(?,?,?,?,?,?,?,?,?)',(targets[0]['id'],alias,event,event_key(scope['entity_id'],event,kind),source['project'],source['entity'],kind,category,json.dumps(proofs)))
                target_values=[{**{k:t.get(k) for k in ['id','source_id','field','topic','kind','epistemic','value','quote']},'value_text':t.get('value_text',t.get('value',''))} for t in targets]
                detail=dict(source_id=source['id'],action=op['action'],record_kind=op['record_kind'],ordinal=op['ordinal'],claim_id=cid,target_ids=op['target_ids'],target_values=target_values,targets=target_values,quote=op['quote'],event=event,category=category,property=prop,proof_sources=proofs)
                self.db.execute('INSERT INTO claim_operation_audit VALUES(?,?,?)',(source['id'],op_offset+index,json.dumps(detail,ensure_ascii=False)))
                self.db.execute('INSERT INTO audit VALUES(?,?,?,?)',(source['id'],op_offset+index,'operation_'+op['action'],json.dumps(op['target_ids'])))
            for field,action in actions.items():
                if action=='set':self.db.execute('UPDATE pending_updates SET resolved_at=? WHERE project=? AND entity=? AND field=? AND seq<=? AND resolved_at IS NULL',(source['seq'],source['project'],source['entity'],field,source['seq']))
            if not _partial:
                self.db.execute('DELETE FROM pending_claim_changes WHERE source_id=?',(source['id'],))
                self.db.execute('DELETE FROM pending_operation_changes WHERE source_id=?',(source['id'],))
                self.db.execute('UPDATE pending_reminder_changes SET resolved_at=? WHERE source_id=? AND resolved_at IS NULL',(source['seq'],source['id']))
            else:
                for target in handled:
                    self.db.execute('DELETE FROM pending_claim_changes WHERE source_id=? AND target_id=?',(source['id'],target))
                    self.db.execute('DELETE FROM pending_operation_changes WHERE source_id=? AND target_id=?',(source['id'],target))
                    self.db.execute('UPDATE pending_reminder_changes SET resolved_at=? WHERE source_id=? AND target_id=? AND resolved_at IS NULL',(source['seq'],source['id'],target))
            self._create_claim_views(source)
            self.db.execute('UPDATE sources SET proposal=? WHERE id=?',(json.dumps(proposal,ensure_ascii=False),source['id']))
            self.db.execute("UPDATE inbox SET state='done',lease_until=0,error=NULL WHERE id=?",(source['id'],))
            self.bump()
            if _on_commit is not None:_on_commit()
        return 'accepted'

    def _delete_operation_records(self, sid, removed_ids):
        for cid in removed_ids:
            self.db.execute('DELETE FROM claim_semantics WHERE claim_id=?',(cid,))
            self.db.execute('DELETE FROM event_alias_proofs WHERE claim_id=?',(cid,))
            self.db.execute('DELETE FROM pending_operation_changes WHERE target_id=?',(cid,))
        self.db.execute('DELETE FROM pending_operation_changes WHERE source_id=?',(sid,))
        for row in self.db.execute('SELECT rowid,proof_sources FROM event_alias_proofs').fetchall():
            if sid in json.loads(row['proof_sources']):self.db.execute('DELETE FROM event_alias_proofs WHERE rowid=?',(row['rowid'],))
        for row in self.db.execute('SELECT source_id,op_index,detail FROM claim_operation_audit').fetchall():
            if row['source_id']==sid or sid in json.loads(row['detail'])['proof_sources']:
                self.db.execute('DELETE FROM claim_operation_audit WHERE source_id=? AND op_index=?',(row['source_id'],row['op_index']))
