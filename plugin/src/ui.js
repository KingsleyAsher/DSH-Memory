// Bare-package host entry keeps the browser half discoverable independently
// of whether the optional memory agent preset is currently active.
import {defineTool} from '@deepseek-ai/dsh-tools';
import {createUserMessage,BlockAssembler} from '@deepseek-ai/dsh-llm';
import {BasicCompactionEngine} from '@deepseek-ai/dsh-compaction-basic';
import {MemoryRuntime} from './runtime.js';
export const name = 'dsh-memory-ui';
export function apply(ctx) {
  ctx.inject(['memoryStore','agentPresets'],scope=>{
    const installed=new Map();
    const compactors=new WeakSet();
    const attach=async agent=>{
      const registry=scope.get('agentPresets');
      const service=name=>registry.serviceFor(agent,name)??scope.get(name);
      const preset=registry.composedPreset(agent.ctx)??'@default';
      let runtime=installed.get(preset);
      const tools=service('tools');if(!tools)return;
      if(!runtime&&tools.get('memory_submit',agent))return;
      if(!runtime){
        // One runtime per preset tool realm. It observes only agents in that
        // realm, including resumed agents; it does not replace their compactor.
        const facade={tools,llm:service('llm'),logger:scope.logger,effect:scope.effect.bind(scope),
          on(name,handler){
            if(name==='session/event')return ()=>{};
            return scope.on(name,(payload,...rest)=>{
              if(payload?.agent&&(registry.composedPreset(payload.agent.ctx)??'@default')!==preset){const next=rest.at(-1);return typeof next==='function'?next():undefined;}
              return handler(payload,...rest);
            });
          }};
        runtime=new MemoryRuntime(facade,scope.get('memoryStore').bridge,{defineTool,createUserMessage});
        installed.set(preset,runtime);
      }
      await runtime.sync(agent);
      const engine=service('compaction');
      if(engine instanceof BasicCompactionEngine&&!compactors.has(engine)){
        const descriptor=Object.getOwnPropertyDescriptor(engine,'summarize');
        const summarize=function(input,current,signal){return runtime.summarize(this,input,current,signal,BlockAssembler);};
        scope.effect(()=>{
          Object.defineProperty(engine,'summarize',{value:summarize,writable:true,configurable:true});
          compactors.add(engine);
          return ()=>{if(engine.summarize===summarize){if(descriptor)Object.defineProperty(engine,'summarize',descriptor);else delete engine.summarize;}compactors.delete(engine);};
        },'memory: augment existing compaction request');
      } else if(engine&&!(engine instanceof BasicCompactionEngine))scope.logger.warn('memory: custom compaction engine requires its own same-call adapter');
    };
    scope.on('agent/created',async({agent})=>{try{await attach(agent);}catch(error){scope.logger.warn('automatic memory attachment deferred: '+error.message);}});
  });
}
