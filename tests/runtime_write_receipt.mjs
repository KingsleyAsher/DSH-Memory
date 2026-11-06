import assert from 'node:assert/strict';
import {MemoryRuntime} from '../plugin/src/runtime.js';
import {CoreBridge} from '../plugin/src/bridge.js';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
const tools=new Map();
let reply;
const ctx={effect:fn=>fn(),tools:{register:tool=>{tools.set(tool.name,tool);return()=>{};}},on:()=>{},logger:{warn:()=>{}}};
const runtime=new MemoryRuntime(ctx,{request:async()=>reply},{defineTool:x=>x,createUserMessage:x=>x});
runtime.active.set('s',[{batch_id:'b',session:'s'}]);
const call=()=>tools.get('memory_submit').execute({batch_id:'b',memory:{items:[],skips:[]}},{agent:{session:{id:'s'}}});
reply={state:'not_saved',can_confirm_saved:false,results:[{state:'rejected'}]};
await assert.rejects(call(),/MEMORY_NOT_SAVED/);
reply={state:'partial',can_confirm_saved:false};
await assert.rejects(call(),/MEMORY_NOT_SAVED/);
reply={state:'saved',can_confirm_saved:true};
assert.deepEqual(await call(),reply);
console.log('PASS: rejected/partial writes fail the host tool; only confirmed saved returns success');

// Exercise the real immutable-response store, not just a mocked tool result.
// All sources and the database are synthetic and isolated from installed data.
const home=await mkdtemp(path.join(os.tmpdir(),'memory-retry-'));
const actual=new CoreBridge({home,coreRoot:path.resolve('.')});
try {
  const registered=new Map();
  let history=[];
  const testCtx={...ctx,tools:{register:tool=>{registered.set(tool.name,tool);return()=>{};}}};
  const testRuntime=new MemoryRuntime(testCtx,actual,{defineTool:x=>x,createUserMessage:x=>({id:crypto.randomUUID(),role:'user',...x})});
  const user={id:'synthetic-user',role:'user',source:{kind:'user'},content:[{type:'text',text:'以后任务成品默认存放到 D:\\Synthetic\\Deliverables。'}]};
  const agent={session:{id:'synthetic-retry',seq:0,header:{cwd:'synthetic-project'},deriveMessages:()=>history,snapshotEvents:()=>[]}};
  const step=async messages=>{
    const decision=await testRuntime.beforeStep(agent,{kind:'enter',messages},new AbortController().signal);
    history.push(...decision.messages);
    return decision.messages.findLast(m=>m.source?.kind==='dsh-memory');
  };
  const contracts=message=>JSON.parse(message.content[0].text.split('\n').at(-1)).memory_contracts;
  const first=contracts(await step([user]))[0];
  assert.equal(await step([]),undefined,'unused visible contracts can be reused');
  const body=value=>({items:[{id:'S1',f:[{v:value,e:[1],a:'成品目录',t:'文件归档',f:'path'}],o:[{op:'assert',n:'F0'}]}],skips:[]});
  const submit=(batch_id,memory)=>registered.get('memory_submit').execute({batch_id,memory},{agent});
  await assert.rejects(submit(first.batch_id,body('D:\\Wrong\\Deliverables')),/MEMORY_NOT_SAVED/);
  const retry=contracts(await step([]))[0];
  assert.notEqual(retry.batch_id,first.batch_id,'rejected answers must expose a fresh batch');
  // A changed answer on the old batch must remain prohibited by the core.
  await assert.rejects(actual.request('submit',{session:agent.session.id,batch_id:first.batch_id,memory:body('D:\\Synthetic\\Deliverables')}),/memory_flow_first_response_changed/);
  await assert.rejects(submit(first.batch_id,body('D:\\Synthetic\\Deliverables')),/stale or foreign/);
  const refreshed=contracts(await step([]))[0];
  assert.notEqual(refreshed.batch_id,retry.batch_id,'stale attempts must refresh the visible contract too');
  const saved=await submit(refreshed.batch_id,body('D:\\Synthetic\\Deliverables'));
  assert.equal(saved.can_confirm_saved,true);
  assert.equal(saved.state,'saved');
  console.log('PASS: real worker rejected path -> fresh contract -> corrected save; stale refresh and immutable-response protection verified');
} finally {
  await actual.close();
  await rm(home,{recursive:true,force:true});
}
