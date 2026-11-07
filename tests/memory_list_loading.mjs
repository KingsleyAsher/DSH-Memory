import assert from 'node:assert/strict';
import {mock} from 'node:test';
import {createMemoryListLoader} from '../plugin/src/knowledge-memory.js';

let calls=0,updates=0,time=0;
const pending=[];
const provider={protocol:'dsh-memory/v1',cacheInvalidations:true,snapshot:({session,purpose})=>{
  assert.equal(purpose,'memory-management');
  calls++;return new Promise((resolve,reject)=>pending.push({session,resolve,reject}));
}};
const loader=createMemoryListLoader({getProvider:()=>provider,changed:()=>updates++,now:()=>time});
const local={project:'synthetic-project',entries:[{id:'synthetic-local'}]};
const flush=()=>new Promise(setImmediate);
assert.equal(loader.load(local,'a').knowledge.state,'loading');
loader.load(local,'a');await flush();assert.equal(calls,1);
assert.equal(loader.load(local,'a').entries[0].id,'synthetic-local');
pending[0].resolve({protocol:'dsh-memory/v1',complete:true,entries:[{id:'synthetic-linked-a'}]});
await flush();assert.equal(loader.load(local,'a').entries.length,2);assert.equal(updates,1);
assert.equal(loader.load(local,'b').entries.length,1);await flush();assert.equal(pending[1].session,'b');
loader.invalidate();
pending[1].resolve({protocol:'dsh-memory/v1',complete:true,entries:[{id:'synthetic-invalidated'}]});
await flush();assert.equal(updates,1,'invalidated work must not restore withdrawn data');
assert.equal(loader.load(local,'a').knowledge.state,'loading');await flush();
pending[2].reject(Error('synthetic offline'));await flush();
assert.equal(loader.load(local,'a').knowledge.state,'unavailable');
assert.equal(loader.load(local,'a').entries.length,1);
time=30001;assert.equal(loader.load(local,'a').knowledge.state,'loading');await flush();
pending[3].resolve({protocol:'dsh-memory/v1',complete:false,entries:[]});await flush();
assert.equal(loader.load(local,'a').knowledge.state,'unavailable','partial snapshots must not be published');
let current=provider;
const disconnect=createMemoryListLoader({getProvider:()=>current,changed:()=>updates++});
disconnect.load(local,'a');await flush();current=null;
assert.equal(disconnect.load(local,'a').knowledge.state,'standalone');
const before=updates;pending[4].resolve({protocol:'dsh-memory/v1',complete:true,entries:[{id:'synthetic-disconnected'}]});
await flush();assert.equal(updates,before);
console.log('PASS: immediate local records, coalescing, session isolation, invalidation, expiry, incomplete/offline snapshots and provider removal');

mock.timers.enable({apis:['setTimeout']});
try{
  for(const recovery of ['ready event','retry timer']){
    let ready=false,reads=0,revisions=0;
    const reconnectingProvider={protocol:'dsh-memory/v1',async snapshot(){
      reads++;
      if(!ready)throw Object.assign(Error('service reconnecting'),{code:'HOST_UNAVAILABLE'});
      return {protocol:'dsh-memory/v1',complete:true,entries:[{id:'synthetic-recovered'}]};
    }};
    const reconnecting=createMemoryListLoader({getProvider:()=>reconnectingProvider,changed:()=>revisions++});
    reconnecting.load(local,'history');await flush();
    assert.equal(reconnecting.load(local,'history').knowledge.state,'reconnecting');
    assert.deepEqual(reconnecting.load(local,'history').entries,local.entries);
    assert.equal(reads,1);
    ready=true;
    if(recovery==='ready event'){
      // The store's provider subscription invalidates on connection readiness.
      reconnecting.invalidate();
      mock.timers.tick(3000);
      assert.equal(revisions,1,'readiness cancels the fallback timer');
    }else{
      mock.timers.tick(2999);assert.equal(revisions,1);
      mock.timers.tick(1);assert.equal(revisions,2,'retry wakes the page');
    }
    assert.equal(reconnecting.load(local,'history').knowledge.state,'loading');
    await flush();
    assert.equal(reconnecting.load(local,'history').knowledge.state,'connected');
    assert.deepEqual(reconnecting.load(local,'history').entries.map(e=>e.id),['synthetic-local','synthetic-recovered']);
    assert.equal(reads,2);
  }
}finally{mock.timers.reset();}
console.log('PASS: transient service failure waits with local entries, then reloads on readiness or fallback retry');

let cacheTime=0;
const cachedReads=[];
const cachedProvider={protocol:'dsh-memory/v1',cacheInvalidations:true,snapshot:()=>new Promise(resolve=>cachedReads.push(resolve))};
let cachedRevisions=0;
const cached=createMemoryListLoader({getProvider:()=>cachedProvider,changed(){cachedRevisions++;},now:()=>cacheTime});
const snapshot=id=>({protocol:'dsh-memory/v1',complete:true,entries:[{id}]});
mock.timers.enable({apis:['setTimeout']});
try{
  cached.load(local,'same-session');await flush();
  cachedReads[0](snapshot('previous'));await flush();
  cacheTime=90000;mock.timers.tick(cacheTime);
  assert.equal(cachedRevisions,1,'idle time must not schedule a reload');
  assert.deepEqual(cached.load(local,'same-session').entries.map(e=>e.id),['synthetic-local','previous']);
  assert.equal(cached.load(local,'same-session').knowledge.state,'connected');
  await flush();assert.equal(cachedReads.length,1,'reopening reuses the snapshot without a read');
}finally{mock.timers.reset();}
cached.invalidate();
assert.equal(cached.load(local,'same-session').knowledge.state,'loading');
await flush();
cached.invalidate();cachedReads[1](snapshot('withdrawn'));await flush();
assert.deepEqual(cached.load(local,'same-session').entries,local.entries);
assert.equal(cached.load(local,'same-session').knowledge.state,'loading');
await flush();cachedReads[2](snapshot('authorized'));await flush();
assert.deepEqual(cached.load(local,'same-session').entries.map(e=>e.id),['synthetic-local','authorized']);
console.log('PASS: reopening reuses the authorized snapshot, and invalidation removes it immediately');

mock.timers.enable({apis:['setTimeout']});
try{
  let reads=0,revisions=0;
  const legacyProvider={protocol:'dsh-memory/v1',async snapshot(){return snapshot('legacy-'+(++reads));}};
  const legacy=createMemoryListLoader({getProvider:()=>legacyProvider,changed:()=>revisions++});
  legacy.load(local,'legacy-session');await flush();
  mock.timers.tick(29999);assert.equal(revisions,1);
  mock.timers.tick(1);assert.equal(revisions,2);
  assert.equal(legacy.load(local,'legacy-session').entries.at(-1).id,'legacy-1');
  await flush();
  assert.equal(legacy.load(local,'legacy-session').entries.at(-1).id,'legacy-2');
  legacy.invalidate();
}finally{mock.timers.reset();}
console.log('PASS: older providers retain the bounded refresh');
