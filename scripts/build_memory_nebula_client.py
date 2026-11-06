"""Compile the approved graph as a sandboxed, local-only plugin view."""
from pathlib import Path
import base64,json,re
root=Path(__file__).resolve().parents[1]
preview=(root/'plugin-ui/nebula-source.html').read_text(encoding='utf-8')
start=preview.index('    const groups=');end=preview.index('    const cached=',start)
bootstrap='''    const memories=MEMORY_PAYLOAD;
    const groups=[],nodes=[],edges=[],pageSize=7,groupColors=['#c4a0ff','#72dfff','#ffc383','#79e3b4','#f3a9ce'];
    const labels={topic:'同类型',reference:'共同来源片段',cross:'跨区块关联',similar:'语义相似'};
    memories.forEach((m,i)=>{const key=m.scope==='global'?'global:'+ (m.metadata?.kind||'其他'):'project:'+m.project+':'+(m.metadata?.kind||'其他');let gi=groups.findIndex(g=>g.key===key);if(gi<0){gi=groups.length;groups.push({key,name:m.scope==='global'?'全局 · '+(m.metadata?.kind||'记忆'):'项目 · '+(m.metadata?.kind||'记忆')});}const a=gi*2.399,c=groups[gi],rank=nodes.filter(n=>n.group===gi).length,t=rank*2.399,r=rank?40+Math.sqrt(rank)*20:0;nodes.push({id:i,entryId:m.id,name:m.title,body:m.text,quote:m.quote||'',scope:m.scope,group:gi,history:false,origin:m.origin==='manual'?'手动添加':'自动收录',source:(m.proofs||[]).map(p=>p.source_id||p.message_id||'').filter(Boolean).join(' · ')||'已入档记忆',anchor:rank===0,pos:[Math.cos(a)*140+Math.cos(t)*r,Math.sin(a)*115+Math.sin(t)*r,Math.sin(gi*1.7+rank)*65]});});
    if(nodes.length>1&&nodes.length<=8){nodes.forEach((n,i)=>{const a=2.8+(i-1)*2.399;n.pos=i?[Math.cos(a)*210,Math.sin(a)*150,Math.sin(i)*25]:[65,0,0];});}
    if(nodes.length){const mean=[0,1,2].map(k=>nodes.reduce((sum,n)=>sum+n.pos[k],0)/nodes.length);nodes.forEach(n=>{n.pos=n.pos.map((v,k)=>v-mean[k]);});}
    // A layout group is not evidence. Only recorded, identical source spans link memories.
    const signatures=m=>(m.proofs||[]).filter(p=>p.source_id&&p.quote).map(p=>String(p.source_id)+'\\0'+String(p.quote));
    const refs=memories.map(signatures);const inverted=new Map;
    refs.forEach((rs,i)=>rs.forEach(k=>{const peers=inverted.get(k)||[];peers.push(i);inverted.set(k,peers);}));
    memories.forEach((m,i)=>(m.metadata?.relations||[]).forEach(rel=>{const b=memories.findIndex(n=>n.id===rel.to);if(b>=0)edges.push({a:i,b,type:nodes[i].group===nodes[b].group?'reference':'cross',reason:rel.reason||'知识库记忆关联'});}));
    const pairs=new Set;inverted.forEach(peers=>{for(let j=1;j<peers.length;j++){const a=peers[0],b=peers[j],key=a+':'+b;if(pairs.has(key))continue;pairs.add(key);edges.push({a,b,type:nodes[a].group===nodes[b].group?'reference':'cross',reason:'两条记忆具有相同的已记录来源片段；共同来源不表示互相证明。'});}});
'''
preview=preview[:start]+bootstrap+preview[end:]
preview=preview.replace("'“'+n.body+'”'","n.quote?'“'+n.quote+'”':'没有独立保存的原文片段。'")
preview=preview.replace('设计预览 · 示例数据','').replace(' · 当前项目：晨星','')
preview=preview.replace('</style>','#dsh-memory-workbench .mw-chrome,#dsh-memory-workbench .mw-heading{display:none}#dsh-memory-workbench .mw-filters{padding-top:16px}#dsh-memory-workbench .mw-map-info{left:20px}#dsh-memory-workbench .mw-map{height:calc(100vh - 160px);min-height:420px}#dsh-memory-workbench .mw-detail{max-height:calc(100vh - 105px);overflow:auto}</style>',1)
preview=preview.replace('</style>',(root/'plugin-ui/full-height.css').read_text(encoding='utf-8')+'</style>',1)
theme=(root/'plugin-ui/nebula-theme.css').read_text(encoding='utf-8')
for token,name in [('DAYLIGHT_ASSET','daylight-nebula.webp'),('PEARL_ASSET','pearl-node.webp')]:
 theme=theme.replace(token,'data:image/webp;base64,'+base64.b64encode((root/'plugin-ui/assets'/name).read_bytes()).decode())
preview=preview.replace('</style>',theme+'</style>',1)
preview=preview.replace('</div>\n  <div class="mw-main">','<button class="mw-button mw-add-top" data-add-top>添加记忆</button></div>\n  <div class="mw-main">',1)
preview=preview.replace('<aside class="mw-detail" aria-label="记忆详情">','<aside class="mw-detail" aria-label="记忆详情"><p class="mw-inspector-title">记忆详情</p>')
# Read the palette once per draw for both canvas edges and DOM nodes.
preview=preview.replace('function draw(){', "function draw(){for(let i=0;i<groupColors.length;i++)groupColors[i]=color('--mw-group-'+i);")
preview=preview.replace("b.dataset.scope=n.scope;","b.dataset.scope=n.scope;b.style.setProperty('--pearl-hue',[0,-65,-100,-45,-20][n.group%5]+'deg');")
preview=preview.replace("button.className='mw-relation cursor-interaction';","button.className='mw-relation cursor-interaction';button.title=edge.reason;button.setAttribute('aria-label',other.name+'，'+edge.reason);")
preview=preview.replace('ctx.shadowBlur=on?12:0;',"ctx.shadowBlur=document.documentElement.dataset.mwTheme==='light'?0:on?12:0;")
preview=preview.replace('width>=640&&state.zoom>=1.2','width>=640&&(nodes.length<=8||state.zoom>=1.2)')
preview=preview.replace("render();\n    if(globalThis.Tweak)", """window.addEventListener('message',ev=>{if(ev.source!==parent||ev.data?.type!=='dsh-memory:theme'||!['light','dark'].includes(ev.data.theme))return;document.documentElement.dataset.mwTheme=ev.data.theme;draw();});
    render();
    if(globalThis.Tweak)""")
preview=preview.replace("q('[data-add]').onclick=()=>{q('.mw-add').hidden=false;q('.mw-add input').focus();};", "q('[data-add]').onclick=()=>parent.postMessage({type:'dsh-memory:add'},'*');")
preview=preview.replace("q('[data-add]').onclick=()=>parent.postMessage({type:'dsh-memory:add'},'*');","q('[data-add-top]').onclick=q('[data-add]').onclick=()=>parent.postMessage({type:'dsh-memory:add'},'*');")
# Hide the preview input; the parent opens the real durable manual-entry dialog.
preview=preview.replace('<form class="mw-add" hidden>','<form class="mw-add" hidden inert>')
preview=preview.replace("const cached=window.openai?.widgetState?.privateContent?.nebulaV1?window.openai.widgetState.privateContent:null;",'const cached=null;')
preview=preview.replace("origin:'手动添加'", "origin:'手动添加'")
doc='<!doctype html><html lang="zh-CN" data-mw-theme="NEBULA_THEME"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="margin:0">'+preview+'</body></html>'
client=root/'plugin/src/client.js';s=client.read_text(encoding='utf-8')
s=s.replace("e(NebulaView,{entries,onAdd:()=>{setDraftScope(scope);setOpen(true);}})","e(NebulaView,{entries:data.entries,onAdd:()=>{setDraftScope(data.project?'project':'global');setOpen(true);}})")
s=s.replace("className: 'dm-toolbar',hidden:!['graph','list'].includes(view)","className: 'dm-toolbar',hidden:view!=='list'")
# Normalize earlier generated integration hooks before rebuilding.
s=re.sub(r"(?:const \[view,setView\]=R.useState\('graph'\);\s*)+",'',s)
begin=s.find('    // BEGIN NEBULA VIEW');end=s.find('    // END NEBULA VIEW')
if begin>=0:s=s[:begin]+s[end+len('    // END NEBULA VIEW'):]
code='''    // BEGIN NEBULA VIEW
    const DAYLIGHT_HOST_STYLE = "body:not([data-ds-dark-theme]) .dm-inner>.dm-tabs{height:56px;gap:28px;padding:0 28px;border:0;border-bottom:1px solid #e5e7f0;background:#fff;align-items:stretch}body:not([data-ds-dark-theme]) .dm-inner>.dm-tabs .dm-tab{border-radius:0;background:transparent;padding:0 2px;font-size:15px;color:#30394b;border-bottom:2px solid transparent}body:not([data-ds-dark-theme]) .dm-inner>.dm-tabs .dm-tab[aria-pressed=true]{color:#5459ad;border-bottom-color:#666abd}";
    const NEBULA_DOCUMENT = DOC_LITERAL;
    function NebulaView({entries,onAdd}) {
      const ref=R.useRef(null);
      const hostTheme=()=>document.body.hasAttribute('data-ds-dark-theme')?'dark':'light';
      const syncTheme=()=>ref.current?.contentWindow?.postMessage({type:'dsh-memory:theme',theme:hostTheme()},'*');
      const src=R.useMemo(()=>NEBULA_DOCUMENT.replace('NEBULA_THEME',hostTheme()).replace('MEMORY_PAYLOAD',JSON.stringify(entries).replace(/</g,'\\\\u003c')), [entries]);
      R.useEffect(()=>{const observer=new MutationObserver(syncTheme);observer.observe(document.body,{attributes:true,attributeFilter:['data-ds-dark-theme']});syncTheme();return()=>observer.disconnect();},[]);
      R.useEffect(()=>{const receive=ev=>{if(ev.source===ref.current?.contentWindow&&ev.data?.type==='dsh-memory:add')onAdd();};window.addEventListener('message',receive);return()=>window.removeEventListener('message',receive);},[onAdd]);
      return e('iframe',{ref,onLoad:syncTheme,title:'记忆关系星云',sandbox:'allow-scripts',srcDoc:src,style:{width:'100%',height:1040,border:0,display:'block',background:'var(--dm-bg)'}});
    }
    // END NEBULA VIEW
'''.replace('DOC_LITERAL',json.dumps(doc,ensure_ascii=False))
s=s.replace('    function MemoryPage() {',code+'\n    function MemoryPage() {')
if not re.search(r'const \[view,\s*setView\]\s*=\s*R.useState',s):
 s=s.replace("const [scope, setScope] = R.useState('global');", "const [view,setView]=R.useState('graph');\n      const [scope, setScope] = R.useState('global');")
if 'e(NebulaView,' not in s:
 s=s.replace("e('div', { className: 'dm-toolbar' },", "e('div',{className:'dm-tabs','aria-label':'记忆视图'},['graph','list'].map(v=>e('button',{key:v,className:'dm-tab','aria-pressed':view===v,onClick:()=>setView(v)},v==='graph'?'关系网':'全部条目'))),\n        view==='graph' && e(NebulaView,{entries:data.entries,onAdd:()=>{setDraftScope(data.project?'project':'global');setOpen(true);}}),\n        e('div', { className: 'dm-toolbar',hidden:view!=='list' },",1)
s=s.replace("e('div', { className: 'dm-list' },", "e('div', { className: 'dm-list',hidden:view!=='list' },",1)
s=s.replace("e('header', { className: 'dm-header' },", "e('header', { className: 'dm-header',hidden:view==='graph' },")
s=s.replace("e('div', { className: 'dm-scope-note' },", "e('div', { className: 'dm-scope-note',hidden:view==='graph' },")
s=s.replace("height:1040", "height:'calc(100vh - 62px)'")
fullscreen='.dm-page{padding:0!important}.dm-inner{max-width:none!important;width:100%}.dsh-memory [hidden]{display:none!important}.dm-inner>.dm-tabs{border-radius:0;padding:6px 18px}.dm-list,.dm-toolbar,.dm-scope-note,.dm-header{margin:16px 24px}.dm-page iframe{min-height:580px}'
s=s.replace('    let client;',"    const FULLSCREEN_STYLE = "+json.dumps(fullscreen)+";\n    let client;",1) if 'const FULLSCREEN_STYLE' not in s else s
s=s.replace('style.textContent = STYLE;', 'style.textContent = STYLE + FULLSCREEN_STYLE;')
if 'style.textContent += DAYLIGHT_HOST_STYLE;' not in s:
 s=s.replace('document.head.appendChild(style);','style.textContent += DAYLIGHT_HOST_STYLE; document.head.appendChild(style);')
stretch='.dm-page{height:100%;min-height:0}.dm-inner{height:100%;display:flex;flex-direction:column}.dm-inner>.dm-tabs{flex:0 0 auto}.dm-page iframe{flex:1 1 0;height:0!important;min-height:0!important}.dm-list{overflow:auto}'
s=s.replace('style.textContent = STYLE + FULLSCREEN_STYLE;', 'style.textContent = STYLE + FULLSCREEN_STYLE + '+json.dumps(stretch)+';')
client.write_text(s,encoding='utf-8')
print('Compiled real-data nebula view:',len(s.encode()),'bytes')
