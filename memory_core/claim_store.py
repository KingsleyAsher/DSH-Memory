"""Program-owned atomic claim metadata and narrowly targeted lifecycle edges."""
import copy
import json
import re

from .contract import normalize, sha, validate_fact
from .contextual import validate_point,retrieval_point
from .policy import SCOPED_FIELDS, VALUE_FIELDS
from .views import canonical_event
from .event_identity import OperationLedger
from .reminders import is_event_reminder, reminder_label, reminder_change_clauses, grounded_reminder_change, pending_role_compatible, non_mutating_reminder_reference, CHANGE, REMINDER


def claim_slot(source, kind, field, topic, attribute):
    return json.dumps([source['project'], source['entity'], kind, field, topic, attribute],
                      ensure_ascii=False, separators=(',', ':'))


def withdrawal_clauses(text):
    """Only positive withdrawal clauses; a negated reminder is not an action."""
    result = []
    for fragment in re.finditer(r'[^。！？!?\n；;，,]+[。！？!?\n；;，,]?', text):
        clause = fragment.group()
        for match in re.finditer(r'撤回|撤掉|收回|作废|撤销|不再采信', clause):
            before = clause[max(0, match.start()-12):match.start()]
            if re.search(r'未|没有|并没|不是|并非|不要|不能|不应|别|不曾|并不|没(?:有)?要', before):
                continue
            if re.search(r'是否|要不要|会不会|能否', before) or re.search(r'[？?]', clause):
                continue
            result.append(clause)
            break
    return result


def names_target(text, target):
    topic = target.get('topic', '').strip()
    value = target.get('value', '').strip()
    return bool((len(topic) >= 2 and topic in text) or (len(value) >= 4 and value in text))


class ClaimStore(OperationLedger):
    def _init_claim_store(self):
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS memory_claims(
            id TEXT PRIMARY KEY,source_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
            record_kind TEXT NOT NULL,attribute TEXT NOT NULL,lifetime TEXT NOT NULL,
            slot TEXT NOT NULL,valid_to INTEGER,superseded_by TEXT,
            UNIQUE(source_id,ordinal,record_kind));
        CREATE INDEX IF NOT EXISTS memory_claims_source ON memory_claims(source_id,record_kind);
        CREATE TABLE IF NOT EXISTS pending_claim_changes(
            source_id TEXT NOT NULL,seq INTEGER NOT NULL,target_id TEXT NOT NULL,
            PRIMARY KEY(source_id,target_id));
        CREATE TABLE IF NOT EXISTS pending_reminder_changes(
            source_id TEXT NOT NULL,seq INTEGER NOT NULL,target_id TEXT NOT NULL,resolved_at INTEGER,
            PRIMARY KEY(source_id,target_id));
        ''')
        self._init_operation_ledger()
        self._migrate_claim_metadata()

    def _migrate_claim_metadata(self, source_id=None):
        # Preserve old lifecycle state, including previously invalidated rows.
        query='SELECT * FROM sources'
        args=()
        if source_id is not None:
            query+=' WHERE id=?'
            args=(source_id,)
        for source in self.db.execute(query+' ORDER BY seq',args).fetchall():
            source = dict(source)
            if not self.visible_source(source['id']):
                continue
            proposal = json.loads(source['proposal'] or '{}')
            legacy = proposal.get('facts', [])
            specs = proposal.get('claim_specs', [])
            for row in self.db.execute('''SELECT f.* FROM facts f WHERE f.source_id=?
                    AND NOT EXISTS(SELECT 1 FROM memory_claims m WHERE m.id=f.id) ORDER BY f.id''', (source['id'],)).fetchall():
                fact = dict(row)
                ordinal = next((i for i in range(len(legacy)) if sha(source['id']+':'+str(i))[:20] == fact['id']), None)
                if ordinal is None:
                    ordinal = next((i for i, f in enumerate(legacy) if all(f.get(k) == fact.get(k) for k in ['field','topic','kind','epistemic','quote','value_text'])), 0)
                spec = specs[ordinal] if ordinal < len(specs) else {}
                attribute = spec.get('attribute') or ('legacy:unknown' if fact['field'] in ['other','preference'] else fact['field'])
                ordinal = spec.get('ordinal', ordinal)
                self.db.execute('INSERT OR IGNORE INTO memory_claims VALUES(?,?,?,?,?,?,?,?,?)',
                    (fact['id'], source['id'], ordinal, 'fact', attribute, spec.get('lifetime','project'),
                     claim_slot(source, fact['kind'], fact['field'], fact['topic'], attribute), fact['valid_to'], fact['superseded_by']))
            for index, point in enumerate(proposal.get('linked_points', [])):
                spec = proposal.get('linked_specs', [])[index] if index < len(proposal.get('linked_specs', [])) else {}
                ordinal = spec.get('ordinal', index)
                attribute = spec.get('attribute', 'legacy:unknown')
                if self.db.execute('SELECT 1 FROM memory_claims WHERE source_id=? AND ordinal=? AND record_kind=?',
                                   (source['id'],ordinal,'linked')).fetchone():
                    continue
                self.db.execute('INSERT OR IGNORE INTO memory_claims VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                    (sha(source['id']+':link:'+str(ordinal))[:20], source['id'], ordinal, 'linked', attribute,
                     spec.get('lifetime','project'), claim_slot(source,'fact','other','',attribute)))

    def _pending_claim_ids(self, at):
        ids = {r['target_id'] for r in self.db.execute('''
            SELECT p.target_id FROM pending_claim_changes p
            JOIN controls c ON c.source_id=p.source_id
            WHERE p.seq<=? AND c.excluded=0 AND c.deleted=0
            AND (c.withdrawn_at IS NULL OR c.withdrawn_at>?)''', (at,at))}
        ids.update(r['target_id'] for r in self._pending_reminder_rows(at))
        ids.update(r['target_id'] for r in self.db.execute('''SELECT p.target_id FROM pending_operation_changes p
            JOIN controls c ON c.source_id=p.source_id WHERE p.seq<=? AND c.excluded=0 AND c.deleted=0
            AND (c.withdrawn_at IS NULL OR c.withdrawn_at>?)''',(at,at)))
        return ids

    def _pending_reminder_rows(self,at,source_id=None):
        # Older pending records may have blanketed all assertions on one topic.
        # Keep their audit rows, but only enforce the axis actually being changed.
        rows=self.db.execute('''SELECT p.*,i.payload,f.topic,f.value_text,m.attribute
            FROM pending_reminder_changes p JOIN inbox i ON i.id=p.source_id
            JOIN controls c ON c.source_id=p.source_id JOIN facts f ON f.id=p.target_id
            JOIN memory_claims m ON m.id=f.id
            WHERE p.seq<=? AND (p.resolved_at IS NULL OR p.resolved_at>?)
            AND c.excluded=0 AND c.deleted=0 AND (c.withdrawn_at IS NULL OR c.withdrawn_at>?)
            AND (? IS NULL OR p.source_id=?) ORDER BY p.seq DESC''',(at,at,at,source_id,source_id)).fetchall()
        return [r for r in rows if json.loads(r['payload']).get('role')=='user'
                and pending_role_compatible(json.loads(r['payload'])['text'],dict(r),r['attribute'])]

    def _mark_pending_reminders(self, source):
        if source['role'] != 'user':
            return
        matched=[]
        possible=[t for t in self.claim_catalog(source) if t['record_kind']=='fact' and is_event_reminder(t,t.get('attribute','')) and reminder_change_clauses(source['text'],t)]
        literal=[t for t in possible if reminder_label(t) in re.sub(r'[\W_的]+','',source['text'])]
        if literal:possible=literal
        elif len({reminder_label(t) for t in possible})>1:possible=[]
        for target in possible:
            matched.extend(reminder_change_clauses(source['text'],target))
            self.db.execute('INSERT OR IGNORE INTO pending_reminder_changes(source_id,seq,target_id) VALUES(?,?,?)',
                            (source['id'],source['seq'],target['id']))
        if matched and not re.search(r'每天|每日|日常|日报|早报|全局|默认|配置|例行',source['text']):
            changes=[p.strip() for p in re.split('[。；;，,]',source['text']) if re.search(CHANGE,p)]
            if all(any(p in m for m in matched) for p in changes):
                self.db.execute('DELETE FROM pending_updates WHERE source_id=? AND field=?',(source['id'],'reminder_time'))

    def reminder_controls(self, at, project=None, entity=None):
        rows=self._pending_reminder_rows(at)
        controls=[];seen=set()
        for row in rows:
            source=json.loads(row['payload'])
            if project is not None and source['project']!=project or entity is not None and source['entity']!=entity:continue
            target=self.db.execute('SELECT * FROM facts WHERE id=?',(row['target_id'],)).fetchone()
            if not target or not self.visible_source(target['source_id']):continue
            target=dict(target)
            if target['seq']>at or target['valid_to'] is not None and target['valid_to']<=at:continue
            label=reminder_label(target)
            if not label or label in seen:continue
            seen.add(label)
            scope=self.register_scope(source['project'],source['entity'])
            controls.append(dict(id='reminder-barrier:'+row['source_id']+':'+row['target_id'],source_id=row['source_id'],seq=row['seq'],
                project=source['project'],entity=source['entity'],project_id=scope['project_id'],entity_id=scope['entity_id'],event_id='',
                field='other',topic=target['topic'],kind='fact',epistemic='unknown',value='',value_text='该提醒变更尚未完成入档',
                quote=source['text'],control=True,reminder_event=True,valid_to=None))
        return controls

    def _mark_pending_retractions(self, source):
        if source['role'] not in ['user','tool']:
            return
        clauses = withdrawal_clauses(source['text'])
        if not clauses:
            return
        for target in self.claim_catalog(source):
            if target['record_kind']=='fact' and target['epistemic']=='hypothesis' and any(names_target(c,target) for c in clauses):
                self.db.execute('INSERT OR IGNORE INTO pending_claim_changes VALUES(?,?,?)',
                                (source['id'],source['seq'],target['id']))

    def claim_by_ref(self, source_id, ordinal, record_kind):
        if type(ordinal) is not int or ordinal < 0 or record_kind not in ['fact','linked']:
            return None
        row = self.db.execute('SELECT id FROM memory_claims WHERE source_id=? AND ordinal=? AND record_kind=?',
                              (source_id, ordinal, record_kind)).fetchone()
        return row['id'] if row else None

    def _raw_claim_evidence(self, source_id, at=None):
        """Immutable visible text is evidence even if its extraction failed."""
        row=self.db.execute('SELECT payload,sha,state FROM inbox WHERE id=?',(source_id,)).fetchone()
        if not row or row['state']=='deleted' or not self.visible_source(source_id,at):return None
        source=json.loads(row['payload'])
        if source.get('id')!=source_id or sha(source.get('text',''))!=row['sha']:return None
        if at is not None and source['seq']>at:return None
        return source

    def _linked_records(self, at=10**12, project=None, entity=None, earliest=False):
        records = []
        for row in self.db.execute('SELECT * FROM sources WHERE seq<=? ORDER BY seq', (at,)).fetchall():
            source = dict(row)
            proof_at=source['seq'] if earliest else at
            if not self.visible_source(source['id'],proof_at) or not source['proposal']:
                continue
            if project is not None and source['project']!=project or entity is not None and source['entity']!=entity:
                continue
            proposal = json.loads(source['proposal'])
            for index, point in enumerate(proposal.get('linked_points', [])):
                specs = proposal.get('linked_specs', [])
                ordinal = specs[index].get('ordinal',index) if index < len(specs) else index
                meta = self.db.execute('SELECT * FROM memory_claims WHERE source_id=? AND ordinal=? AND record_kind=?',
                                       (source['id'], ordinal, 'linked')).fetchone()
                if not meta or not earliest and meta['valid_to'] is not None and meta['valid_to']<=at:
                    continue
                refs = []
                for evidence in point.get('evidence', []):
                    ref = self.db.execute('SELECT * FROM sources WHERE id=?', (evidence.get('source_id'),)).fetchone()
                    ref=dict(ref) if ref else self._raw_claim_evidence(evidence.get('source_id'),proof_at)
                    if not ref or not self.visible_source(ref['id'],proof_at):
                        break
                    refs.append(ref)
                else:
                    try:
                        validate_point(point, source, refs)
                    except (ValueError,TypeError,KeyError):
                        continue
                    current_quote = next((e['quote'] for e in point['evidence'] if e['source_id']==source['id']), '')
                    projected=retrieval_point(dict(id=meta['id'],source_id=source['id'],seq=source['seq'],
                        project=source['project'],entity=source['entity'],field='other',topic='',kind='fact',
                        epistemic=point['epistemic'],value=point['statement'],quote=current_quote,
                        attribute=meta['attribute'],lifetime=meta['lifetime'],slot=meta['slot'],record_kind='linked',point=point,
                        valid_to=meta['valid_to'],superseded_by=meta['superseded_by']))
                    projected=self._decorate_operation_claim(projected,proof_at)
                    if projected:records.append(projected)
        return records

    def claim_catalog(self, source):
        at = source['seq']-1
        result = []
        # Pending targets are hidden from answers but remain addressable by a
        # later explicit update. They are not silently treated as current values.
        for fact in self.scoped_facts(at,source['project'],source['entity'],include_pending=True):
            meta = self.db.execute('SELECT * FROM memory_claims WHERE id=?', (fact['id'],)).fetchone()
            if not meta or meta['valid_to'] is not None and meta['valid_to']<=at:
                continue
            result.append({**fact,'attribute':meta['attribute'],'lifetime':meta['lifetime'],
                           'slot':meta['slot'],'record_kind':'fact','pending':fact['id'] in self._pending_claim_ids(at)})
        result.extend(self._linked_records(at,source['project'],source['entity']))
        return sorted(result,key=lambda r:(r['seq'],r['id']))

    def _validated_actions(self, source, result, diagnostics):
        # Empty semantic_actions is a deliberate no-op, never a keyword fallback.
        if 'semantic_actions' not in result:
            return {}
        proposed = result.get('semantic_actions')
        if not isinstance(proposed,dict):
            raise ValueError('semantic_actions_shape')
        actions = {}
        for item in result.get('semantic_review',{}).get('actions',[]):
            if (isinstance(item,dict) and item.get('field') in VALUE_FIELDS
                    and item.get('action') in ['set','pending','unchanged','planned','not_applicable']
                    and isinstance(item.get('quote'),str) and item['quote']
                    and item['quote'] in source['text'] and proposed.get(item['field'])==item['action']):
                actions[item['field']] = item['action']
            else:
                diagnostics.append(dict(reason='semantic_action_provenance'))
        return actions

    @staticmethod
    def _validate_specs(records, specs):
        if not isinstance(records,list) or not isinstance(specs,list) or len(records)!=len(specs):
            raise ValueError('claim_spec_alignment')
        seen = set()
        for spec in specs:
            if (not isinstance(spec,dict) or set(spec)!={'attribute','lifetime','replace_ids','ordinal'}
                    or not isinstance(spec['attribute'],str) or not spec['attribute'].strip()
                    or spec['attribute']!=spec['attribute'].strip() or len(spec['attribute'])>80
                    or spec['lifetime'] not in ['project','global']
                    or not isinstance(spec['replace_ids'],list) or any(not isinstance(x,str) or not x for x in spec['replace_ids'])
                    or type(spec['ordinal']) is not int or spec['ordinal']<0 or spec['ordinal'] in seen):
                raise ValueError('claim_spec_shape')
            seen.add(spec['ordinal'])

    def finish_atomic(self, source, result, linked_context=None, *, strict=False):
        """Persist one source, its claims, edges and done marker in one transaction."""
        if 'mutation_contract' in result:
            return self._finish_operations(source,result,linked_context)
        source, result = copy.deepcopy(source), copy.deepcopy(result)
        inbox = self.db.execute('SELECT * FROM inbox WHERE id=?', (source['id'],)).fetchone()
        if not inbox or inbox['state']=='deleted' or inbox['sha']!=sha(source['text']):
            raise ValueError('source_unavailable_or_changed')
        saved = json.loads(inbox['payload'])
        if any(saved.get(k)!=source.get(k) for k in ['id','seq','project','entity','role','text']):
            raise ValueError('source_identity_changed')
        if not self.visible_source(source['id']):
            raise ValueError('source_not_visible')
        old = self.db.execute('SELECT sha,state FROM sources WHERE id=?', (source['id'],)).fetchone()
        if old:
            if old['sha']!=sha(source['text']):
                raise ValueError('source_id_changed')
            return old['state']
        facts, specs = result.get('facts',[]), result.get('claim_specs',[])
        points, point_specs = result.get('linked_points',[]), result.get('linked_specs',[])
        self._validate_specs(facts,specs)
        self._validate_specs(points,point_specs)
        diagnostics = list(result.get('diagnostics',[]))
        actions = self._validated_actions(source,result,diagnostics) if source['role'] in ['user','tool'] else {}
        accepted, linked = [], []
        context = self.recent_dialogue(source) if linked_context is None else linked_context
        visible_context = []
        for ref in context:
            row = self.db.execute('SELECT * FROM sources WHERE id=?',(ref['id'],)).fetchone()
            session = self.db.execute('SELECT session_id FROM inbox WHERE id=?',(ref['id'],)).fetchone()
            evidence=self._raw_claim_evidence(ref['id']) if strict else dict(row) if row else None
            if evidence and session and self.visible_source(ref['id']) and session['session_id']==saved.get('session_id','default'):
                visible_context.append(evidence)
        for fact, spec in zip(facts,specs):
            try:
                validate_fact(source['text'],fact)
                if source['role'] not in ['user','tool']:
                    raise ValueError('assistant_not_long_term_fact')
                if fact['kind']=='fact' and actions.get(fact['field'])=='pending' and normalize(fact['field'],fact['value_text'])!='__unset__':
                    raise ValueError('pending_value_not_current')
                if fact['field'] in SCOPED_FIELDS:
                    fact['topic'] = canonical_event(fact['topic'])
                accepted.append((fact,spec))
            except (ValueError,TypeError,KeyError) as exc:
                diagnostics.append(dict(reason=str(exc),fact=fact))
        for point, spec in zip(points,point_specs):
            try:
                if source['role']!='user':
                    raise ValueError('linked_confirmation_required')
                linked.append((validate_point(point,source,visible_context),spec))
            except (ValueError,TypeError,KeyError) as exc:
                diagnostics.append(dict(reason=str(exc),point=point))
        if strict and diagnostics:
            raise ValueError('atomic_source_rejected:'+json.dumps(diagnostics,ensure_ascii=False))
        # Catalog deliberately includes this source's narrowly pending targets:
        # the pending guard hides retrieval, but cannot block its own resolution.
        with self.db:
            self.db.execute('DELETE FROM pending_claim_changes WHERE source_id=?',(source['id'],))
            catalog = {r['id']:r for r in self.claim_catalog(source)}
            retained=[]
            for record_kind,pairs in [('fact',accepted),('linked',linked)]:
                for record,spec in pairs:
                    matching=[t for t in catalog.values() if is_event_reminder(t,t.get('attribute','')) and non_mutating_reminder_reference(source,record,t)]
                    quote=record.get('quote','') or next((e['quote'] for e in record.get('evidence',[]) if e['source_id']==source['id']),'')
                    literal=[t for t in matching if reminder_label(t) in re.sub(r'[\W_的]+','',quote)]
                    allowed=literal or matching if literal or len({reminder_label(t) for t in matching})==1 else []
                    ids=[cid for cid in spec['replace_ids'] if cid in {t['id'] for t in allowed}]
                    if ids:
                        spec['replace_ids']=[cid for cid in spec['replace_ids'] if cid not in ids]
                        retained.append(dict(record_kind=record_kind,ordinal=spec['ordinal'],target_ids=ids))
            # An omitted model binding must not clear a known targeted change
            # and revive the old request as current. Model-selected targets are
            # checked below and all writes remain inside this source transaction.
            required={r['target_id'] for r in self._pending_reminder_rows(source['seq'],source['id'])}
            proposed={t for _,s in accepted for t in s['replace_ids']}
            if strict and required-proposed:
                raise ValueError('unresolved_event_reminder_update:'+','.join(sorted(required-proposed)))
            state = 'partial' if diagnostics and (accepted or linked) else 'parked' if diagnostics else 'accepted'
            proposal = {**result,'facts':[f for f,_ in accepted],'claim_specs':[s for _,s in accepted],
                        'linked_points':[p for p,_ in linked],'linked_specs':[s for _,s in linked],
                        'pending_fields':sorted(f for f,a in actions.items() if a=='pending'),
                        'semantic_actions':actions,'diagnostics':diagnostics,
                        'session_points':result.get('session_points',[]),'retained_target_refs':retained}
            self.db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                (source['id'],source['seq'],source['project'],source['entity'],source['role'],source['text'],sha(source['text']),state,
                 json.dumps(diagnostics,ensure_ascii=False) if diagnostics else None,json.dumps(proposal,ensure_ascii=False)))
            self.db.execute('DELETE FROM pending_updates WHERE source_id=?',(source['id'],))
            self.db.execute('INSERT OR REPLACE INTO source_reviews VALUES(?,?,?)',
                (source['id'],json.dumps(actions),json.dumps(result.get('semantic_review',{}),ensure_ascii=False)))
            for item in retained:
                self.db.execute('INSERT INTO audit VALUES(?,?,?,?)',(source['id'],item['ordinal'],'retain_reference',json.dumps(item['target_ids'])))
            for field, action in actions.items():
                if action=='pending':
                    self.db.execute('INSERT INTO pending_updates VALUES(?,?,?,?,?,NULL)',
                                    (source['id'],source['seq'],source['project'],source['entity'],field))
            for record_kind, pairs in [('fact',accepted),('linked',linked)]:
                for record, spec in pairs:
                    ordinal = spec['ordinal']
                    cid = sha(source['id']+(':claim:' if record_kind=='fact' else ':link:')+str(ordinal))[:20]
                    field = record['field'] if record_kind=='fact' else 'other'
                    topic = record['topic'] if record_kind=='fact' else ''
                    kind = record['kind'] if record_kind=='fact' else 'fact'
                    reminder_targets=[catalog[t] for t in spec['replace_ids'] if t in catalog and is_event_reminder(catalog[t],catalog[t].get('attribute',''))]
                    if reminder_targets:
                        same_identity=len({t['slot'] for t in reminder_targets})==1
                        mentioned=[t for t in catalog.values() if is_event_reminder(t,t.get('attribute','')) and reminder_change_clauses(record.get('quote',''),t)]
                        literal=[t for t in mentioned if reminder_label(t) in re.sub(r'[\W_的]+','',record.get('quote',''))]
                        allowed={t['id'] for t in (literal or mentioned)}
                        unambiguous=bool(literal) or len({reminder_label(t) for t in mentioned})==1
                        safe=(record_kind=='fact' and len(reminder_targets)==len(set(spec['replace_ids'])) and same_identity
                              and unambiguous and {t['id'] for t in reminder_targets}<=allowed
                              and all(grounded_reminder_change(source,record,t) for t in reminder_targets))
                        if not safe:
                            diagnostics.append(dict(reason='event_reminder_update_not_grounded',ids=spec['replace_ids']))
                            continue
                        # The target ID is the model's semantic binding. Its
                        # stable event/property owns the slot, not a fresh label.
                        canonical=reminder_targets[0]
                        later=self.db.execute('''SELECT f.id FROM facts f JOIN memory_claims m ON m.id=f.id
                            JOIN controls c ON c.source_id=f.source_id
                            WHERE m.slot=? AND f.seq>? AND c.excluded=0 AND c.deleted=0 AND c.withdrawn_at IS NULL LIMIT 1''',
                            (canonical['slot'],source['seq'])).fetchone()
                        if later:
                            diagnostics.append(dict(reason='late_event_reminder_update_requires_review',id=later['id']))
                            continue
                        record['topic']=canonical['topic'];spec['attribute']=canonical['attribute']
                        topic=record['topic']
                    slot = claim_slot(source,kind,field,topic,spec['attribute'])
                    if record_kind=='fact':
                        self.db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (cid,source['id'],source['seq'],source['project'],source['entity'],field,topic,kind,record['epistemic'],
                             normalize(field,record['value_text']),record['value_text'],record['quote'],None,None))
                        if field in SCOPED_FIELDS:
                            self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?)',(source['project'],source['entity'],kind,topic,topic))
                    self.db.execute('INSERT INTO memory_claims VALUES(?,?,?,?,?,?,?,NULL,NULL)',
                                    (cid,source['id'],ordinal,record_kind,spec['attribute'],spec['lifetime'],slot))
                    safe_set = record_kind=='fact' and field in VALUE_FIELDS and kind=='fact' and record['epistemic']=='stated' and actions.get(field)=='set'
                    target_ids = list(dict.fromkeys(spec['replace_ids']))
                    if safe_set:
                        target_ids.extend(t['id'] for t in catalog.values() if t['record_kind']=='fact' and t['kind']==kind and t['field']==field and t['topic']==topic)
                    replaced = []
                    for target_id in dict.fromkeys(target_ids):
                        target = catalog.get(target_id)
                        scalar_compatible = target and field in VALUE_FIELDS and target['field']==field and target['topic']==topic
                        if not target or target['kind']!=kind or (target['slot']!=slot and not scalar_compatible):
                            diagnostics.append(dict(reason='replacement_target_not_same_live_slot',id=target_id))
                            continue
                        self._invalidate_claim(target_id,source['seq'],cid)
                        replaced.append(target_id)
                    if safe_set:
                        self.db.execute('UPDATE pending_updates SET resolved_at=? WHERE project=? AND entity=? AND field=? AND seq<=? AND resolved_at IS NULL',
                                        (source['seq'],source['project'],source['entity'],field,source['seq']))
                    self.db.execute('INSERT INTO audit VALUES(?,?,?,?)',
                                    (source['id'],ordinal,'replace' if replaced else 'assert',json.dumps(replaced)))
            hypotheses = [r for r in catalog.values() if r['record_kind']=='fact' and r['epistemic']=='hypothesis']
            for request in result.get('retract_claims',[]):
                target = catalog.get(request.get('id')) if isinstance(request,dict) else None
                quote = request.get('quote') if isinstance(request,dict) else None
                clauses = withdrawal_clauses(quote) if isinstance(quote,str) and quote and quote in source['text'] else []
                named = [h for h in hypotheses if any(names_target(c,h) for c in clauses)]
                if (source['role'] not in ['user','tool'] or not target or target['record_kind']!='fact'
                        or target['epistemic']!='hypothesis' or not clauses
                        or named and target['id'] not in {h['id'] for h in named}):
                    diagnostics.append(dict(reason='retraction_not_explicit_live_hypothesis',request=request))
                    continue
                self._invalidate_claim(target['id'],source['seq'],'retract:'+source['id'])
                self.db.execute('INSERT INTO audit VALUES(?,?,?,?)',(source['id'],0,'retract_hypothesis',json.dumps([target['id']])))
            self._create_claim_views(source)
            # Diagnostics added while checking lifecycle targets are persisted too.
            state = 'partial' if diagnostics and (accepted or linked) else 'parked' if diagnostics else 'accepted'
            proposal['diagnostics'] = diagnostics
            self.db.execute('UPDATE sources SET state=?,error=?,proposal=? WHERE id=?',
                (state,json.dumps(diagnostics,ensure_ascii=False) if diagnostics else None,json.dumps(proposal,ensure_ascii=False),source['id']))
            for i,item in enumerate(diagnostics):
                self.db.execute('INSERT INTO audit VALUES(?,?,?,?)',(source['id'],i,'rejected_item',json.dumps(item,ensure_ascii=False)))
            if strict and diagnostics:
                # Raise inside this source's transaction: facts, lifecycle edges,
                # pending guards and its done marker must all roll back together.
                raise ValueError('atomic_source_rejected:'+json.dumps(diagnostics,ensure_ascii=False))
            self.db.execute("UPDATE inbox SET state='done',lease_until=0,error=NULL WHERE id=?",(source['id'],))
            self.bump()
        return state

    def _invalidate_claim(self, claim_id, seq, successor):
        self.db.execute('UPDATE memory_claims SET valid_to=?,superseded_by=? WHERE id=? AND (valid_to IS NULL OR valid_to>?)',
                        (seq,successor,claim_id,seq))
        self.db.execute('UPDATE facts SET valid_to=?,superseded_by=? WHERE id=? AND (valid_to IS NULL OR valid_to>?)',
                        (seq,successor,claim_id,seq))
        self.db.execute('DELETE FROM derived WHERE source_id IN (SELECT source_id FROM memory_claims WHERE id=?)',(claim_id,))
        self.db.execute('UPDATE pending_reminder_changes SET resolved_at=? WHERE target_id=? AND seq<=? AND (resolved_at IS NULL OR resolved_at>?)',
                        (seq,claim_id,seq,seq))

    def _create_claim_views(self, source):
        events = {}
        for row in self.db.execute('SELECT * FROM facts WHERE source_id=?',(source['id'],)):
            if row['field'].startswith('incident_'):
                events.setdefault((row['topic'],row['kind']),[]).append(dict(row))
        for records in events.values():
            if len({r['field'] for r in records})>1:
                for row in records[:3]:
                    self.db.execute('INSERT OR IGNORE INTO views VALUES(?,?,?,?,?)',
                        (sha(row['id']+':view')[:20],source['id'],row['quote'],row['field'],json.dumps([row['id']])))
