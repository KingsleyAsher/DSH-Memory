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
import { createMemoryListLoader } from './knowledge-memory.js';

const OPS = {
  activate: 'scope_activate', current: 'scope_current', list: 'manual_list',
  add: 'manual_add', remove: 'manual_remove',
  reviews: 'review_list', review: 'review_resolve',
  revision: 'revision',
};
const legacyWriteOps=new Set(['submit','commit','manual_add','manual_remove','review_suggest',
  'review_resolve','scope_activate','ingest','recover','status','style_project_put']);

function openMemoryChanges(request, subscribers, readRevision) {
  const {signal}=request;
  const encoder=new TextEncoder();
  let subscriber, remove;
  const body=new ReadableStream({
    start(controller) {
      let sent;
      subscriber={
        send(){
          const value=readRevision();
          if(sent===value.revision||controller.desiredSize<=0)return;
          controller.enqueue(encoder.encode('data: '+JSON.stringify(value)+'\n\n'));
          sent=value.revision;
        },
        close(){remove();controller.close();},
      };
      remove=()=>{
        subscribers.delete(subscriber);
        signal.removeEventListener('abort',subscriber.close);
      };
      if(signal.aborted){controller.close();return;}
      subscribers.add(subscriber);
      signal.addEventListener('abort',subscriber.close,{once:true});
    },
    pull(){subscriber.send();},
    cancel(){remove();},
  });
  return new Response(body,{headers:{'content-type':'text/event-stream','cache-control':'no-store','x-accel-buffering':'no'}});
}
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
    this.bridge = new CoreBridge({ home: stateDir, coreRoot, python: config.python ?? 'python',
      onMemoryChange:()=>this.changed() });
    this.knowledgeState={state:'standalone',entries:[]};
    this.revision=randomUUID();
    const subscribers=new Set();
    const readRevision=()=>({revision:this.revision,listDelta:true});
    this.changed=()=>{
      this.revision=randomUUID();
      for(const subscriber of subscribers){
        try{subscriber.send();}catch(error){ctx.logger.warn('memory change subscriber failed: '+error.message);}
      }
      ctx.emit('memory/changed',{revision:this.revision});
    };
    const listLoader=createMemoryListLoader({getProvider:()=>ctx.get('knowledgeMemory'),changed:()=>this.changed()});
    const listViews=new Map();
    const originalRequest=this.bridge.request.bind(this.bridge);
    this.bridge.request=async(op,args={})=>{
      if(op==='revision')return readRevision();
      const {knowledge_session,list_delta,list_cursor,...workerArgs}=args;
      const revision=this.revision;
      const viewKey=JSON.stringify([workerArgs.window_id,knowledge_session??null]);
      const previous=op==='manual_list'&&list_delta===true?listViews.get(viewKey):undefined;
      const canApplyDelta=previous&&previous.cursor===list_cursor;
      if(canApplyDelta&&previous.revision===revision&&previous.view.knowledge?.state!=='unavailable'){
        return {cursor:previous.cursor,unchanged:true};
      }
      const result=await originalRequest(op,workerArgs);
      if(!this.bridge.reportsMemoryChanges&&legacyWriteOps.has(op))this.changed();
      if(op==='manual_add'&&list_delta===true)return {state:result.state};
      if(op!=='manual_list'&&op!=='query')return result;
      if(op==='manual_list'){
        const view=listLoader.load(result,knowledge_session);
        if(list_delta!==true)return view;
        const cursor=randomUUID();
        listViews.delete(viewKey);
        if(listViews.size>=8)listViews.delete(listViews.keys().next().value);
        listViews.set(viewKey,{cursor,revision,view});
        if(!canApplyDelta)return {...view,cursor};
        const old=new Map(previous.view.entries.map(entry=>[entry.id,entry]));
        const ids=new Set(view.entries.map(entry=>entry.id));
        const removed=[...old.keys()].filter(id=>!ids.has(id));
        const upsert=view.entries.filter(entry=>JSON.stringify(old.get(entry.id))!==JSON.stringify(entry));
        const order=view.entries.map(entry=>entry.id);
        const sameOrder=order.length===old.size&&[...old.keys()].every((id,index)=>id===order[index]);
        return {project:view.project,knowledge:view.knowledge,cursor,delta:{upsert,removed,...(sameOrder?{}:{order})}};
      }
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
    this.memoryApi={
      version:1,
      request:async(operation,args={},requestId)=>{
        switch(operation){
          case 'global.list':return this.globalRequest('list',args,requestId);
          case 'global.add':return this.globalRequest('add',args,requestId);
          case 'global.remove':return this.globalRequest('remove',args,requestId);
          case 'conversation.style.get':return this.bridge.request('style_project_get',{project:args.project});
          case 'conversation.style.put':return this.bridge.request('style_project_put',{project:args.project,profile:args.profile});
          default:throw Error('unknown_memory_integration_operation');
        }
      },
      subscribe:listener=>{
        const subscriber={send:()=>listener(readRevision())};
        subscriber.send();
        subscribers.add(subscriber);
        return ()=>subscribers.delete(subscriber);
      },
    };
    ctx.effect(()=>()=>{
      for(const subscriber of subscribers)subscriber.close?.();
      subscribers.clear();
    },'memory: release integration subscriptions');
    ctx.inject(['knowledgeMemory'],scope=>{
      listLoader.invalidate();
      const off=scope.get('knowledgeMemory')?.subscribe?.(event=>{
        if(event?.event==='dsh.event')return;
        listLoader.invalidate();
        this.changed();
      });
      if(off)scope.effect(()=>off,'memory: knowledge changes');
      scope.effect(()=>()=>{listLoader.invalidate();this.changed();},'memory: discard knowledge list snapshots');
      this.changed();
    });
    ctx.effect(() => () => this.bridge.close(), 'memory: stop shared private worker');
    ctx.effect(() => { void this.bridge.request('recover').catch(e => ctx.logger.warn('memory recovery deferred: ' + e.message)); return () => {}; }, 'memory: restore durable work');
    // Connection owns browser authentication, Origin validation and owner-only
    // admission. Do not register an unauthenticated webServer route.
    ctx.inject(['connection'], scope => {
      scope.connection.fetch.register({ path: '/api/dsh-memory', methods: ['GET','POST'], requestBody: 'buffered',
        fetch: request => request.method==='GET'
          ? openMemoryChanges(request,subscribers,readRevision)
          : handleMemoryRequest(this.bridge,request,updates) });
      scope.effect(()=>()=>{for(const subscriber of subscribers)subscriber.close?.();},'memory: close change subscriptions');
    });
  }
}
