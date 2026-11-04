"""Pinned local MiMo and optional free BGE; never auto-download or switch."""
import hashlib,json,subprocess,time
from pathlib import Path
import numpy as np
from . import ollama_client
from .contract import sha

class LocalModel:
    context_window=4096
    def __init__(self,store=None):self.store=store;self.calls=0;self.cache_hits=0;self.info=None
    def inspect(self):
        if self.info is None:self.info=ollama_client.inspect()
        return self.info
    def call(self,system,payload,schema,*,max_tokens=640,source_id='query',cache=False):
        info=self.inspect();key=sha(json.dumps(dict(system=system,payload=payload,schema=schema,tokens=max_tokens,digest=info['digest']),ensure_ascii=False,sort_keys=True))
        if cache and self.store:
            old=self.store.db.execute('SELECT response FROM model_cache WHERE key=?',(key,)).fetchone()
            if old:self.cache_hits+=1;return {**json.loads(old[0]),'cache_hit':True}
        self.calls+=1;out=ollama_client.chat(system,payload,schema,max_tokens=max_tokens)
        if cache and self.store:
            with self.store.db:self.store.db.execute('INSERT OR REPLACE INTO model_cache VALUES(?,?,?)',(key,source_id,json.dumps(out,ensure_ascii=False)))
        return {**out,'cache_hit':False}

class BGE:
    model='BAAI/bge-m3';dim=1024
    def __init__(self):self.calls=0;self.texts=0;self.wall_ms=0
    def embed(self,texts):
        if not texts:return []
        if len(texts)>16:raise ValueError('embedding batch exceeds 16')
        script=Path(__file__).with_name('embed.mjs');started=time.perf_counter()
        out=subprocess.run(['node',str(script)],input=json.dumps(dict(texts=texts),ensure_ascii=False),capture_output=True,text=True,encoding='utf-8',timeout=95)
        self.calls+=1;self.texts+=len(texts);self.wall_ms+=(time.perf_counter()-started)*1000
        if out.returncode:raise RuntimeError('fixed BGE-M3 request failed; no alternate provider')
        value=json.loads(out.stdout)
        if value.get('model')!=self.model:raise ValueError('wrong embedding model')
        vectors=[]
        for row in value['vectors']:
            v=np.asarray(row,dtype=np.float32)
            if v.shape!=(self.dim,) or not np.all(np.isfinite(v)) or np.linalg.norm(v)==0:raise ValueError('invalid BGE vector')
            vectors.append(v/np.linalg.norm(v))
        if len(vectors)!=len(texts):raise ValueError('embedding count mismatch')
        return vectors
