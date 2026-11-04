import { BasicCompactionEngine } from '@deepseek-ai/dsh-compaction-basic';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { BlockAssembler, createUserMessage } from '@deepseek-ai/dsh-llm';
import { MemoryRuntime } from './runtime.js';

export const name = 'dsh-memory';
export const inject = ['memoryStore', 'agents', 'tools', 'systemPrompt', 'llm', 'sessions', 'tokenMeter'];
export function apply(ctx, config = {}) {
  const bridge = ctx.memoryStore.bridge;
  const runtime = new MemoryRuntime(ctx, bridge, { defineTool, createUserMessage }, config);
  class MemoryCompactionEngine extends BasicCompactionEngine {
    summarize(input, agent, signal) { return runtime.summarize(this, input, agent, signal, BlockAssembler); }
  }
  // Replace the basic backend via bundle patch; never mutate its implementation.
  ctx.plugin(MemoryCompactionEngine, config.compaction ?? {});
  return runtime;
}
