import {createUpdateChecker,createUpdateDownloader} from './updates.js';
import {pluginDetails} from './details.js';
import {readFileSync} from 'node:fs';
import { Service } from '@deepseek-ai/cordis';
import { resolve, isAbsolute } from 'node:path';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';
import { CoreBridge } from './bridge.js';
import { randomUUID } from 'node:crypto';

const OPS = {
  activate: 'scope_activate', current: 'scope_current', list: 'manual_list',
  add: 'manual_add', remove: 'manual_remove',
  reviews: 'review_list', review: 'review_resolve',
  revision: 'revision',
};
export async function handleMemoryRequest(bridge, request, updates) {
  try {
    const text = await request.text();
    if (text.length > 24000) return Response.json({ error: '输入过长' }, { status: 413 });
    const body = JSON.parse(text);
    if(body.op==='details')return Response.json(updates.details);
    if(body.op?.startsWith('updates.')) {
      if(body.op==='updates.check')return Response.json(await updates.checker.check({force:!!body.args?.force}));
      if(body.op==='updates.prepare')return Response.json(await updates.downloader.prepare({expectedVersion:body.args?.expectedVersion}));
      throw Error('unknown_update_operation');
    }
    const op = OPS[body.op];
    if (!op || !body.args || typeof body.args.window_id !== 'string') throw new Error('invalid_memory_request');
    const value = await bridge.request(op, body.args);
    return Response.json(value);
  } catch (error) {
    return Response.json({ error: error.message }, { status: 400 });
  }
}

export default class MemoryStore extends Service {
  conversationScopeVersion = 1;
  chatStyleVersion = 1;
  constructor(ctx, config = {}) {
    super(ctx, 'memoryStore');
    const packageInfo=JSON.parse(readFileSync(new URL('../package.json',import.meta.url),'utf8'));
    const currentVersion=packageInfo.version;
    const profile=ctx.get('profileContext');
    const checker=createUpdateChecker({currentVersion});
    const downloader=createUpdateDownloader({checker,cacheDir:profile?.dir?resolve(profile.dir,'.memory-plugin-updates'):null});
    const updates={checker,downloader,details:pluginDetails(packageInfo)};
    // Cordis rejects undeclared service property reads, even before ?? fallback.
    // Use its optional lookup and a durable home-relative default.
    const stateDir = config.stateDir || resolve(ctx.get('baseDir') ?? resolve(process.env.DSH_HOME || resolve(homedir(), '.dsh'), 'storages'), 'memory-beta-state');
    if (!isAbsolute(stateDir)) throw new Error('stateDir must be absolute');
    const bundled = fileURLToPath(new URL('../python/', import.meta.url));
    const coreRoot = config.coreRoot ?? (existsSync(resolve(bundled, 'memory_core')) ? bundled : fileURLToPath(new URL('../../', import.meta.url)));
    this.bridge = new CoreBridge({ home: stateDir, coreRoot, python: config.python ?? 'python' });
    this.knowledgeState={state:'standalone',entries:[]};
    this.revision=randomUUID();
    this.changed=()=>{this.revision=randomUUID();ctx.emit('memory/changed',{revision:this.revision});};
    const originalRequest=this.bridge.request.bind(this.bridge);
    this.bridge.request=async(op,args={})=>{
      if(op==='revision')return {revision:this.revision};
      const {knowledge_session,...workerArgs}=args;
      const result=await originalRequest(op,workerArgs);
      if(['submit','commit','manual_add','manual_remove','review_resolve','scope_activate','ingest','recover','style_project_put'].includes(op))this.changed();
      if(op!=='manual_list'&&op!=='query')return result;
      const provider=ctx.get('knowledgeMemory');
      if(!provider||provider.protocol!=='dsh-memory/v1'){this.knowledgeState={state:'standalone',entries:[]};return {...result,knowledge:{state:'standalone'}};}
      try{
        const snapshot=await provider.snapshot({session:op==='query'?args.session:knowledge_session});
        if(snapshot.protocol!=='dsh-memory/v1'||snapshot.complete!==true)throw Error('incomplete_memory_snapshot');
        this.knowledgeState={state:'connected',entries:snapshot.entries};
        if(op==='query'){
          const question=String(args.question||'').toLowerCase();
          const terms=[...new Set(question.match(/[a-z0-9]+|[\u4e00-\u9fff]{2}/g)||[])];
          const candidates=snapshot.entries.map(e=>({entry:e,score:terms.reduce((n,t)=>n+(e.title+' '+e.text).toLowerCase().includes(t),0)})).filter(e=>e.score>0).sort((a,b)=>b.score-a.score).slice(0,4).map(({entry:e})=>({source_id:e.id,value:e.text,quote:e.quote,scope:e.scope,origin:'knowledge',revision:e.metadata.revision}));
          return originalRequest('knowledge_merge',{result,candidates});
        }
        return {...result,entries:[...result.entries,...snapshot.entries],knowledge:{state:'connected',count:snapshot.entries.length}};
      }catch(error){this.knowledgeState={state:'unavailable',entries:[]};return {...result,knowledge:{state:'unavailable',error:error.message}};}
    };
    // The knowledge service never receives project windows, source transcripts,
    // worker operations or caller-selected scope keys. All clients use these
    // same global records; this creates no second memory database.
    this.globalRequest=async(op,args={},requestId)=>{
      const window_id='knowledge-global-v1';
      if(op==='list'){
        const result=await originalRequest('manual_list',{window_id});
        return {...result,revision:this.revision,entries:result.entries.filter(e=>e.scope==='global')};
      }
      if(op==='add')return this.bridge.request('manual_add',{window_id,scope:'global',text:args.text,title:args.title??'',request_id:requestId});
      if(op==='remove'){
        const list=await originalRequest('manual_list',{window_id});
        if(!list.entries.some(e=>e.id===args.entry_id&&e.scope==='global'))throw Error('memory_not_in_global_scope');
        return this.bridge.request('manual_remove',{window_id,entry_id:args.entry_id});
      }
      throw Error('unknown_global_memory_operation');
    };
    ctx.inject(['knowledgeMemory'],scope=>{
      const off=scope.get('knowledgeMemory')?.subscribe?.(()=>this.changed());
      if(off)scope.effect(()=>off,'memory: knowledge changes');
      this.changed();
    });
    ctx.effect(() => () => this.bridge.close(), 'memory: stop shared private worker');
    ctx.effect(() => { void this.bridge.request('recover').catch(e => ctx.logger.warn('memory recovery deferred: ' + e.message)); return () => {}; }, 'memory: restore durable work');
    // Connection owns browser authentication, Origin validation and owner-only
    // admission. Do not register an unauthenticated webServer route.
    ctx.inject(['connection'], scope => {
      scope.connection.fetch.register({ path: '/api/dsh-memory', methods: ['POST'], requestBody: 'buffered',
        fetch: request => handleMemoryRequest(this.bridge, request, updates) });
    });
  }
}
