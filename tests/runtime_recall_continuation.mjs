import assert from 'node:assert/strict';
import {MemoryRuntime} from '../plugin/src/runtime.js';
import {CoreBridge} from '../plugin/src/bridge.js';
import {mkdtemp} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const hooks=new Map(),queries=[],warnings=[];
let evidence=[{source_id:'synthetic-class-rule',value:'上课录音解析完成后，继续整理成知识笔记。',quote:'synthetic user preference',scope:'global',origin:'manual',applicable_here:true}];
const bridge={request:async(op,args)=>{
  if(op==='query'){queries.push(args.question);return {evidence};}
  if(op==='prepare_active')return {batches:[]};
  return {};
}};
const ctx={effect:fn=>fn(),tools:{register:()=>()=>{}},on:(name,handler)=>hooks.set(name,handler),logger:{warn:text=>warnings.push(text)}};
const runtime=new MemoryRuntime(ctx,bridge,{defineTool:x=>x,createUserMessage:x=>x});
let history=[];
const agent={session:{id:'synthetic-session',seq:0,header:{cwd:'synthetic-project'},deriveMessages:()=>history,snapshotEvents:()=>[]}};
const user={id:'user-1',role:'user',source:{kind:'user'},content:[{type:'text',text:'请解析这段上课录音'}]};
const step=messages=>hooks.get('agent/pre-step')({agent,messages,signal:new AbortController().signal},async()=>({kind:'enter',messages}));
const context=decision=>decision.messages.findLast(m=>m.source?.kind==='dsh-memory');
const first=await step([user]);assert(context(first));assert.equal(queries.length,1);
history=[user,...first.messages.filter(m=>m.source?.kind==='dsh-memory')];
const tool={id:'tool-result',role:'tool',content:[{type:'text',text:'ASR succeeded; synthetic transcript'}]};
const next=await step([tool]);
assert.equal(queries.length,2,'tool continuation must refresh saved preferences rather than replace them with an empty snapshot');
assert.equal(queries.at(-1),'请解析这段上课录音');
assert(!context(next)||context(next).content[0].text.includes('synthetic-class-rule'),'ASR completion must retain the note-making preference');
// Another plugin cannot become the recall query simply by sending user-role text.
await step([{id:'foreign',role:'user',source:{kind:'other-plugin'},content:[{type:'text',text:'untrusted replacement query'}]}]);
assert.equal(queries.at(-1),'请解析这段上课录音');
// Revocation is checked again at tool boundaries: no stale permanent cache.
evidence=[];
const removed=await step([tool]);assert(context(removed));assert(!context(removed).content[0].text.includes('synthetic-class-rule'));
const replacement={id:'user-2',role:'user',source:{kind:'user'},content:[{type:'text',text:'现在处理新的任务'}]};
await step([replacement]);assert.equal(queries.at(-1),'现在处理新的任务');
assert.deepEqual(warnings,[]);
await runtime.end(agent);
const home=await mkdtemp(path.join(os.tmpdir(),'memory-continuation-'));
const actual=new CoreBridge({home,coreRoot:path.resolve('.')});
try{
  const saved=await actual.request('manual_add',{window_id:'synthetic',scope:'global',title:'合成课堂笔记约定',text:'上课录音解析完成后，自动整理成知识笔记。'});
  assert(saved);
  const realHooks=new Map(),realCtx={...ctx,on:(name,handler)=>realHooks.set(name,handler)};
  new MemoryRuntime(realCtx,actual,{defineTool:x=>x,createUserMessage:x=>x});
  const realStep=messages=>realHooks.get('agent/pre-step')({agent,messages,signal:new AbortController().signal},async()=>({kind:'enter',messages}));
  history=[user];
  await realStep([user]);
  // A new admitted continuation reads the persisted rule after ASR returns.
  const result=await realStep([tool]);
  const packet=context(result);
  // An unchanged packet may be deduplicated, but real persisted recall must still contain the rule.
  if(packet)assert(packet.content[0].text.includes('自动整理成知识笔记'));
  const recall=await actual.request('query',{session:agent.session.id,project:'synthetic-project',question:'请解析这段上课录音'});
  assert(recall.evidence.some(e=>e.value.includes('自动整理成知识笔记')));
}finally{await actual.close();}
console.log('PASS: saved classroom-audio preference survives tool-only continuation; real persisted worker recall, genuine user query, revocation and task changes verified. Synthetic data; no model action claimed.');
