// One owner follows agents independently of preset names; tools are bound to
// their actual service realms, which can be shared or isolated by presets.
import {defineTool} from '@deepseek-ai/dsh-tools';
import {createUserMessage,BlockAssembler} from '@deepseek-ai/dsh-llm';
import {BasicCompactionEngine} from '@deepseek-ai/dsh-compaction-basic';
import {MemoryRuntime,automaticRuntimes,isMemoryExcluded} from './runtime.js';
export const name = 'dsh-memory-ui';
export function apply(ctx,config={}) {
  ctx.inject(['memoryStore','agentPresets'],scope=>{
    const bridge=scope.get('memoryStore').bridge,registry=scope.get('agentPresets');
    const resolveService=(agent,name)=>registry.serviceFor(agent,name)??scope.get(name);
    const compactorMethods=new WeakSet(),warned=new Set();
    let runtime;
    const attach=agent=>{
      if(isMemoryExcluded(agent.session,config)) return;
      try { runtime.registerTools(resolveService(agent,'tools')); }
      catch(error){
        const warning='memory tools unavailable; recall remains active: '+error.message;
        if(!warned.has(warning)){warned.add(warning);scope.logger.warn(warning);}
      }
      const engine=resolveService(agent,'compaction');
      if(engine instanceof BasicCompactionEngine&&!compactorMethods.has(engine.summarize)){
        const descriptor=Object.getOwnPropertyDescriptor(engine,'summarize');
        const originalSummarize=engine.summarize;
        const summarize=function(input,current,signal){return isMemoryExcluded(current?.session,config) ? originalSummarize.call(this,input,current,signal) : runtime.summarize(this,input,current,signal,BlockAssembler);};
        scope.effect(()=>{
          Object.defineProperty(engine,'summarize',{value:summarize,writable:true,configurable:true});
          compactorMethods.add(summarize);
          return ()=>{if(engine.summarize===summarize){if(descriptor)Object.defineProperty(engine,'summarize',descriptor);else delete engine.summarize;}compactorMethods.delete(summarize);};
        },'memory: augment existing compaction request');
      } else if(engine&&!(engine instanceof BasicCompactionEngine)&&!warned.has(engine.constructor)){
        warned.add(engine.constructor);
        scope.logger.warn('memory: custom compaction engine requires its own same-call adapter; normal recall remains active');
      }
    };
    const facade={logger:scope.logger,effect:scope.effect.bind(scope),on:scope.on.bind(scope),get:scope.get.bind(scope)};
    runtime=new MemoryRuntime(facade,bridge,{defineTool,createUserMessage},
      {...config,registerTools:false,ensureAgent:attach,resolveService});
    automaticRuntimes.set(bridge,runtime);
    scope.effect(()=>()=>{if(automaticRuntimes.get(bridge)===runtime)automaticRuntimes.delete(bridge);},'memory: release automatic owner');
  });
}
