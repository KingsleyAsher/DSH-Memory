import {readFileSync} from 'node:fs'
import {existsSync} from 'node:fs'
import {fileURLToPath,pathToFileURL} from 'node:url'
import path from 'node:path'
const {texts}=JSON.parse(readFileSync(0,'utf8'))
if(!Array.isArray(texts)||texts.length<1||texts.length>16||texts.some(t=>typeof t!=='string'||!t.trim()||t.length>12000))throw Error('Invalid embedding inputs')
let out
const key=process.env.MEMORY_SILICONFLOW_API_KEY
if(key){
 const response=await fetch('https://api.siliconflow.cn/v1/embeddings',{method:'POST',redirect:'error',signal:AbortSignal.timeout(90000),headers:{Authorization:`Bearer ${key}`,'Content-Type':'application/json'},body:JSON.stringify({model:'BAAI/bge-m3',input:texts,encoding_format:'float'})})
 if(!response.ok)throw Error(`Pinned embedding endpoint failed: HTTP ${response.status}`)
 out={result:await response.json()}
}else{
 const bridge=process.env.MEMORY_BGE_BRIDGE
 if(!bridge||!existsSync(bridge))throw Error('Configure MEMORY_SILICONFLOW_API_KEY or an explicit BGE bridge; no alternate model')
 const {call}=await import(pathToFileURL(bridge).href)
 out=await call('embeddings',{model:'BAAI/bge-m3',input:texts,encoding_format:'float'})
}
if(out.result.model!=='BAAI/bge-m3')throw Error('Wrong fixed model')
const rows=[...out.result.data].sort((a,b)=>a.index-b.index)
if(rows.length!==texts.length||rows.some((r,i)=>r.index!==i||r.embedding.length!==1024||r.embedding.some(v=>!Number.isFinite(v))))throw Error('Invalid vectors')
process.stdout.write(JSON.stringify({model:out.result.model,vectors:rows.map(r=>r.embedding)}))
