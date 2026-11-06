import assert from 'node:assert/strict';
import {MemoryRuntime,isPureSession,isMemoryExcluded} from '../plugin/src/runtime.js';

const callbacks = new Map(), requests = [];
const ctx = { on: (name, fn) => callbacks.set(name, fn), effect: () => {}, get: () => undefined,
  logger: { warn: () => {} } };
const runtime = new MemoryRuntime(ctx, {request: async (name) => { requests.push(name); return {}; }},
  {defineTool: x => x, createUserMessage: x => x}, {registerTools: false});
const pure = { session: { id: 'pure-session', header: { agentPreset: 'pure' } } };
const normal = { session: { id: 'normal', header: { agentPreset: 'wechat-chat' } } };
const decision = {kind: 'enter', messages: []}, signal = new AbortController().signal;
assert.equal(isPureSession(pure.session), true);
assert.equal(isPureSession(normal.session), false);
assert.equal(await callbacks.get('agent/pre-step')({agent:pure,signal}, async () => decision), decision);
await runtime.captureDirect(pure.session, [{id:'m',role:'user',source:{kind:'user'},content:[{type:'text',text:'test'}]}]);
assert.deepEqual(requests, []);
let called = false;
runtime.beforeStep = async () => { called = true;return decision; };
await callbacks.get('agent/pre-step')({agent:normal,signal}, async () => decision);
assert.equal(called, true);
console.log('PASS: pure skips pre-step and capture; non-pure still enters memory runtime');
assert(isMemoryExcluded({header:{memoryEnabled:false}}));
assert(isMemoryExcluded({header:{agentPreset:'no-memory'}},{excludedPresets:['no-memory']}));
assert(!isMemoryExcluded({header:{agentPreset:'knowledge'}}));
for(const id of ['standard','knowledge','chat','writer','child-agent','custom-preset'])assert(!isMemoryExcluded({header:{agentPreset:id}}));
const disabled={session:{id:'disabled',header:{memoryEnabled:false}}};called=false;
await callbacks.get('agent/pre-step')({agent:disabled,signal},async()=>decision);assert.equal(called,false);
await runtime.captureDirect(disabled.session,[]);assert.deepEqual(requests,[]);
console.log('PASS: all preset IDs opt in by default; explicit session opt-out skips recall and capture');
