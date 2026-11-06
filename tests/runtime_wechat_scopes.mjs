import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { MemoryRuntime } from '../plugin/src/runtime.js';
import { CoreBridge } from '../plugin/src/bridge.js';

const home = await mkdtemp(path.join(os.tmpdir(), 'memory-wechat-scope-'));
const projectA = 'wechat-conversation:' + 'a'.repeat(64);
const projectB = 'wechat-conversation:' + 'b'.repeat(64);
let bridge = new CoreBridge({ home, coreRoot: path.resolve('.') });
try {
  await bridge.request('scope_bind_conversation', { session: 'chat-a-old', project: projectA });
  const active = await bridge.request('scope_activate', { window_id: 'window-a', project: 'same-cwd', session_id: 'chat-a-old' });
  assert.equal(active.project, projectA, 'opening the memory panel cannot override a bound chat with its cwd');
  await bridge.request('manual_add', { window_id: 'window-a', scope: 'project', title: '合成本群口令', text: '合成本群口令是海风。' });
  await bridge.request('manual_add', { window_id: 'window-a', scope: 'global', title: '合成通用称呼', text: '合成通用称呼是蓝鲸。' });
  await bridge.request('scope_bind_conversation', { session: 'chat-b', project: projectB });
  await assert.rejects(bridge.request('scope_bind_conversation', { session: 'chat-b', project: projectA }), /conversation_scope_cannot_change/);
  // A previously shared cwd session cannot be silently migrated or overwritten.
  await bridge.request('ingest', { session: 'old-cwd-session', project: 'same-cwd', messages: [{ id: 'old', role: 'user', text: '请记住合成旧口令是山风。' }] });
  await bridge.request('ingest', { session: 'old-foreign-session', project: 'same-cwd', messages: [{ id: 'foreign', role: 'user', text: '请记住合成其他群旧口令是星河。' }] });
  await assert.rejects(bridge.request('scope_bind_conversation', { session: 'old-cwd-session', project: projectA }), /requires_new_session/);
  await bridge.close();
  bridge = new CoreBridge({ home, coreRoot: path.resolve('.') });
  const hooks = new Map();
  const ctx = { get: name => name === 'wechatMemoryScope' ? { resolve: id => ({ project: id.startsWith('chat-a') ? projectA : projectB, policy: 'synthetic chat-local/global policy', legacySessionIds: id.startsWith('chat-a') ? ['old-cwd-session'] : [] }) } : undefined,
    on: (name, fn) => hooks.set(name, fn), effect: fn => fn(), logger: { warn: message => { throw new Error(message); } } };
  const runtime = new MemoryRuntime(ctx, bridge, { defineTool: x => x, createUserMessage: x => x }, { registerTools: false });
  const agent = id => ({ session: { id, seq: 0, header: { cwd: 'same-cwd' }, snapshotEvents: () => [], deriveMessages: () => [] } });
  const turn = async (id, question = '合成本群口令和通用称呼是什么') => {
    const message = { id: id + '-user', role: 'user', source: { kind: 'user' }, content: [{ type: 'text', text: question }] };
    return runtime.beforeStep(agent(id), { kind: 'enter', messages: [message] }, new AbortController().signal);
  };
  const text = result => result.messages.filter(m => m.source?.kind === 'dsh-memory').map(m => m.content[0].text).join('\n');
  const restored = text(await turn('chat-a-new-session'));
  assert(restored.includes('合成本群口令是海风'), 'same chat survives a new DSH session and worker restart');
  assert(restored.includes('合成通用称呼是蓝鲸'));
  assert(!restored.includes('合成其他群旧口令是星河'));
  const legacy = text(await turn('chat-a-legacy-session', '山风'));
  assert(legacy.includes('合成旧口令是山风'), 'proven chat-owned legacy memories remain available without reclassifying old data');
  assert(!legacy.includes('合成其他群旧口令是星河'));
  const other = text(await turn('chat-b'));
  assert(!other.includes('合成本群口令是海风'), 'another group with the same cwd must not receive chat A local evidence');
  assert(other.includes('合成通用称呼是蓝鲸'));
  const outside = await bridge.request('query', { session: 'ordinary-agent', project: 'unrelated-project', question: '合成通用称呼' });
  assert(outside.evidence.some(e => e.value.includes('蓝鲸')), 'ordinary DSH agents still share global memory');
  assert(!outside.evidence.some(e => e.value.includes('海风')));
  console.log('PASS synthetic real SQLite/worker: chat-local isolation, shared global recall, new session and restart continuity, window activation protection, old-scope preservation.');
} finally { await bridge.close(); await rm(home, { recursive: true, force: true }); }
