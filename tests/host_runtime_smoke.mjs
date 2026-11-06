import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';


// Supply an isolated host containing official runtime modules and this plugin.
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
const hostRoot=resolve(process.argv[2]||process.env.DSH_TEST_HOST||'.');
const req=createRequire(pathToFileURL(resolve(hostRoot,'package.json')));
const load=spec=>import(pathToFileURL(req.resolve(spec)));
const hostVersion=JSON.parse(await readFile(req.resolve('@deepseek-ai/dsh-tools/package.json'),'utf8')).version;
const cordisVersion=JSON.parse(await readFile(req.resolve('@deepseek-ai/cordis/package.json'),'utf8')).version;
const { Context }=await load('@deepseek-ai/cordis');
const {default:Agents}=await load('@deepseek-ai/dsh-agent');
const {default:Sessions}=await load('@deepseek-ai/dsh-session');
const {default:Projections}=await load('@deepseek-ai/dsh-session-projection');
const {default:Prompt}=await load('@deepseek-ai/dsh-system-prompt');
const {default:Tools}=await load('@deepseek-ai/dsh-tools');
const {default:Llm, LlmAdapter, createUserMessage }=await load('@deepseek-ai/dsh-llm');
const {default:Loop}=await load('@deepseek-ai/dsh-agent-loop');
const {default:Meter}=await load('@deepseek-ai/dsh-token-meter');
const {default:Loader, Group }=await load('@deepseek-ai/cordis-plugin-loader');
const {default:Presets}=await load('@deepseek-ai/dsh-agent-preset-registry');
const {default:MemoryStore}=await load('@local/dsh-memory/store');
let NativeExecutor;
try{NativeExecutor=await load('@deepseek-ai/dsh-tool-executor-native');}
catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
const fixtureRoot=await mkdtemp(resolve(os.tmpdir(),'memory-host-matrix-'));
const {CoreBridge}=await import(pathToFileURL(resolve(hostRoot,'node_modules/@local/dsh-memory/src/bridge.js')));
// No network can be used accidentally by this test's adapter.
globalThis.fetch = () => { throw new Error('NETWORK DISABLED IN HOST SMOKE'); };
const home=resolve(fixtureRoot,'memory');
const calls = []; const checks = []; const warnings = [];
const ctx = new Context();
ctx.on('internal/error', error => { warnings.push(String(error)); });
for (const plugin of [Projections, Sessions, Prompt, Tools, Llm, Agents, Meter, Loop]) ctx.plugin(plugin);
if(NativeExecutor)ctx.plugin(NativeExecutor);
await new Promise(setImmediate);
assert.ok(ctx.agents && ctx.tools && ctx.tokenMeter && ctx.llm);
const oldText = '以后只发文字。不要只靠红绿区分。'; // reused from tests/test_memory_flow.py
let submitted = false;
class FixtureAdapter extends LlmAdapter {
  async resolveModel(provider, model) { return { provider, id: model, name: model, context: { contextWindow: 32768 } }; }
  async *stream(options) {
    calls.push({ purpose: options.purpose ?? 'conversation', messages: options.messages });
    let block;
    if (options.purpose === 'compaction') {
      const instruction = options.messages.at(-1).content[0].text;
      const contracts = JSON.parse(instruction.slice(instruction.indexOf('\n') + 1));
      for (const original of options.messages.slice(0, -1)) {
        assert.equal(options.messages.filter(m => m.id && m.id === original.id).length, 1);
      }
      assert.ok(!instruction.includes(oldText), 'no full-history duplicate in trailing contract');
      const value = { continuation_summary: '继续按文字输出和颜色可辨要求工作。', memories: contracts.map(c => ({ batch_id: c.batch_id, memory: {
        items: c.payload.write_sources.map(id => ({ id, f: [{ v: '不要只靠红绿区分', e: [2], a: '呈现要求', t: '呈现', f: 'pref' }], o: [{ op: 'assert', n: 'F0' }] })), skips: [],
      } })) };
      block = { type: 'text', text: JSON.stringify(value) };
    } else {
      const extra = [...options.messages].reverse().find(m => m.source?.kind === 'dsh-memory');
      const context = extra ? JSON.parse(extra.content[0].text.slice(extra.content[0].text.indexOf('\n') + 1)) : {};
      if (!submitted && context.memory_contracts?.length) {
        submitted = true; const contract = context.memory_contracts[0]; const id = contract.payload.write_sources[0];
        block = { type: 'tool-call', id: 'fixture-memory-call', name: 'memory_submit', arguments: JSON.stringify({
          batch_id: contract.batch_id, memory: { items: [{ id, f: [{ v: '以后只发文字', e: [1], a: '呈现要求', t: '呈现', f: 'pref' }], o: [{ op: 'assert', n: 'F0' }] }], skips: [] },
        }) };
      } else block = { type: 'text', text: '已收到。' };
    }
    yield { type: 'block-start', index: 0, blockType: block.type };
    yield { type: 'block-end', index: 0, block };
    yield { type: 'finish', reason: { kind: 'stop' } };
  }
}
ctx.llm.registerAdapter(['fixture-only'], new FixtureAdapter());
ctx.plugin(Loader, { baseUrl: import.meta.url });
ctx.plugin(Presets, { default: 'memory-beta' });
await new Promise(setImmediate);
ctx.loader.builtins.group = Group;
ctx.plugin(MemoryStore, { stateDir: home, python: 'python' });
const declaration={id:'preset-memory-beta',name:'@deepseek-ai/dsh-agent-preset',config:{id:'memory-beta',name:'Synthetic memory test',plugins:[{id:'memory-beta-compaction',name:'cordis:group',group:true,isolate:{compaction:true},config:[{id:'memory-beta-core',name:'@local/dsh-memory/runtime'}]}]}};
declaration.config.plugins[0].config[0].name = '@local/dsh-memory/runtime';
declaration.config.plugins[0].config[0].config = { stateDir: home, python: 'python', compaction: { auto: false, headroomTokens: 128, maxTokens: 8192, retainTokens: 256 } };
await ctx.loader.create(declaration);
await ctx.loader.await();
assert.ok(!(await ctx.agentPresets.list())[0].broken, JSON.stringify(await ctx.agentPresets.list()));
checks.push('packaged_opt_in_preset_real_loader_activation');
const setup = async scope => { await ctx.agentPresets.mount(scope, 'memory-beta'); };
let first, second; const bridge = new CoreBridge({ home, python: 'python', coreRoot: resolve('.') });
try {
  first = await ctx.agents.create({ sessionId: 'beta-first', meta: { cwd: resolve(fixtureRoot,'workspace') }, agentOptions: { provider: 'fixture-only', model: 'fixture' }, setup });
  await bridge.request('scope_activate', { window_id: 'fixture-window', project: resolve(fixtureRoot,'workspace'), session_id: 'beta-first' });
  first.agent.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: oldText }] }));
  await first.agent.whenIdle();
  const toolResult = first.agent.session.snapshotEvents().find(e => e.type === 'tool/result');
  if (!toolResult) console.log(JSON.stringify({ calls: calls.map(c => c.messages.map(m => ({ id:m.id, role:m.role, source:m.source, content:m.content.map(b=>({type:b.type,text:b.text?.slice(0,160)})) }))), warnings, events: first.agent.session.snapshotEvents().map(e => ({ type: e.type, data: e.type === 'turn/end' || e.type === 'assistant/attempt' ? e.data : undefined })) }));
  assert.ok(toolResult, 'real driver executed the registered tool');
  assert.ok(JSON.stringify(toolResult).includes('saved'), JSON.stringify(toolResult));
  checks.push('real_loop_proactive_submission');
  const before = await bridge.request('query', { session: 'beta-first', question: '答复习惯是什么？', project: resolve(fixtureRoot,'workspace') });
  assert.ok(before.evidence.some(e => e.value.includes('以后只发文字'))); checks.push('persistent_core_write');
  const n = calls.filter(c => c.purpose === 'compaction').length;
  const compaction = ctx.agentPresets.serviceFor(first.agent, 'compaction');
  assert.ok(compaction); assert.equal(ctx.compaction, undefined, 'preset compaction must not leak to host');
  const compacted = await compaction.compactNow(first.agent, new AbortController().signal);
  assert.ok(compacted); assert.equal(calls.filter(c => c.purpose === 'compaction').length - n, 1);
  const event = first.agent.session.snapshotEvents().find(e => e.type === 'compaction/summary');
  assert.ok(event); assert.ok(!JSON.stringify(event.data.summary).includes('batch_id'));
  const after = await bridge.request('query', { session: 'beta-first', question: '答复习惯是什么？', project: resolve(fixtureRoot,'workspace') });
  assert.ok(after.evidence.some(e => e.value.includes('红绿'))); checks.push('one_call_compaction_gap_fill_and_durable_checkpoint');
  second = await ctx.agents.create({ sessionId: 'beta-second', meta: { cwd: resolve(fixtureRoot,'workspace') }, agentOptions: { provider: 'fixture-only', model: 'fixture' }, setup });
  await bridge.request('scope_activate', { window_id: 'fixture-window', project: resolve(fixtureRoot,'workspace'), session_id: 'beta-second' });
  second.agent.followup(createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: '答复习惯是什么？' }] }));
  await second.agent.whenIdle();
  const recall = calls.at(-1).messages.find(m => m.source?.kind === 'dsh-memory');
  assert.ok(recall && recall.content[0].text.includes('以后只发文字')); checks.push('cross_session_automatic_recall');
  const denied = await bridge.request('query', { question: '答复习惯是什么？', project: 'other-workspace' });
  assert.equal(denied.evidence.length, 0); checks.push('workspace_isolation');
  // Dispose the real agent with one pending question, then restart the worker.
  await second.dispose(); second = null;
  await bridge.close();
  const restart = new CoreBridge({ home, python: 'python', coreRoot: resolve('.') });
  const recovery = await restart.request('recover'); assert.ok(recovery.pending_sources >= 1);
  // A resumed native window explicitly binds the new chat to its project.
  const oldProject = await restart.request('scope_activate', { window_id: 'fixture-window', project: resolve(fixtureRoot,'workspace'), session_id: 'beta-second' });
  await restart.request('scope_activate', { window_id: 'fixture-window', project: oldProject.project, session_id: 'beta-third' });
  const resumed = await restart.request('prepare_active', { session: 'beta-third', project: oldProject.project, message_ids: [] });
  assert.ok(resumed.batches.some(b => b.session === 'beta-second')); checks.push('exit_restart_and_same_workspace_backlog_resume');
  const b = resumed.batches[0];
  await assert.rejects(restart.request('submit', { session: 'foreign-session', batch_id: b.batch_id, memory: { items: [], skips: [] } }), /owned/);
  checks.push('foreign_session_submission_rejected');
  const child = restart.child;
  const exited = new Promise(resolve => child.once('exit', resolve));
  child.kill(); await exited;
  const crashRecovery = await restart.request('recover');
  assert.ok(crashRecovery.pending_sources >= 1);
  const retained = await restart.request('query', { session: 'beta-first', question: '答复习惯是什么？', project: resolve(fixtureRoot,'workspace') });
  assert.ok(retained.evidence.some(e => e.value.includes('以后只发文字')));
  checks.push('worker_crash_auto_restart_preserves_memory_and_backlog');
  await restart.close();
  console.log(JSON.stringify({ hostVersion,cordisVersion,passed: checks.length, checks, fixture_stream_calls: calls.length,external_model_calls:0 }));
} finally {
  await second?.dispose(); await first?.dispose(); await bridge.close(); await ctx.fiber.dispose();
  await rm(fixtureRoot,{recursive:true,force:true});
}
