"""Optional shared vectors, grouped candidate paths and fair base reranking."""
import collections,hashlib,json,math,re,time
import numpy as np
from .views import propose,base_text,digest,canonical_event

def grams(text):
    clean=''.join(re.findall(r'[\w\u4e00-\u9fff]+',text.lower()))
    return {clean[i:i+2] for i in range(max(0,len(clean)-1))}
def lexical(query,text):
    q=grams(query);return len(q&grams(text))/max(1,len(q))
def texts_for(unit,cap=4):return [v['text'] for v in propose(unit,cap,True)]
def features(query,unit,vectors,cap=4):
    texts=texts_for(unit,cap);q=vectors.get(query)
    base=vectors.get(texts[0])
    sim=float(q@base) if q is not None and base is not None else 0.0
    # Additional views create candidates, never multiple independent votes or
    # a max-of-four final-score bonus. All candidates use canonical base scoring.
    return np.array([sim,sim,lexical(query,base_text(unit)),0,lexical(query,unit.get('event_key','')),0,0,0],dtype=float)
def rule_score(x):return float(.50*x[0]+.15*x[1]+.20*x[2]+.10*x[3]+.05*x[4])

class Index:
    def __init__(self,store,config,provider=None):self.store=store;self.config=config;self.provider=provider;self.cache={};self.error=None
    def get(self,text):
        key=digest(text)
        if key in self.cache:return self.cache[key]
        r=self.store.db.execute('SELECT data,bytes_sha FROM embeddings WHERE model=? AND dim=? AND text_sha=?',('BAAI/bge-m3',1024,key)).fetchone()
        if not r:return None
        if hashlib.sha256(r['data']).hexdigest()!=r['bytes_sha']:raise ValueError('vector cache integrity failure')
        v=np.frombuffer(r['data'],dtype=np.float32).copy()
        if v.shape!=(1024,) or not np.all(np.isfinite(v)):raise ValueError('vector cache namespace mismatch')
        self.cache[key]=v;return v
    def save(self,text,vector):
        v=np.asarray(vector,dtype=np.float32);b=v.tobytes()
        if v.shape!=(1024,) or not np.all(np.isfinite(v)):raise ValueError('bad vector')
        with self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?)',('BAAI/bge-m3',1024,digest(text),b,hashlib.sha256(b).hexdigest()))
            self.store.db.execute('DELETE FROM index_state WHERE text_sha=?',(digest(text),))
        self.cache[digest(text)]=v
    def ensure(self,units):
        allocations=self.store.sync_views(units,self.config.view_cap,self.config.semantic)
        if not self.config.semantic:return dict(allocations=allocations,new_vectors=0,error=None)
        views=[v for u in units for v in propose(u,self.config.view_cap,True)]
        # Reserve bases before optional views; keep sources when capacity is hit.
        views.sort(key=lambda v:v['purpose']!='base');texts=list(dict.fromkeys(v['text'] for v in views))
        budget=self.config.vector_budget_bytes//4096;existing=self.store.db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0]
        missing=[];now=time.time()
        for text in texts:
            if self.get(text) is not None:continue
            state=self.store.db.execute('SELECT * FROM index_state WHERE text_sha=?',(digest(text),)).fetchone()
            if state and state['retry_after']>now:continue
            if existing+len(missing)>=budget:break
            missing.append(text)
        added=0;self.error=None
        if self.provider:
            for start in range(0,len(missing),16):
                batch=missing[start:start+16]
                try:
                    vectors=self.provider.embed(batch)
                    for text,v in zip(batch,vectors):self.save(text,v);added+=1
                except Exception as exc:
                    self.error=type(exc).__name__+': '+str(exc)[:150]
                    with self.store.db:
                        for text in batch:
                            key=digest(text);old=self.store.db.execute('SELECT attempts FROM index_state WHERE text_sha=?',(key,)).fetchone();attempts=(old[0] if old else 0)+1
                            self.store.db.execute('INSERT OR REPLACE INTO index_state VALUES(?,?,?,?)',(key,attempts,time.time()+min(3600,30*2**min(attempts,7)),self.error))
                    break
        return dict(allocations=allocations,new_vectors=added,pending=max(0,len(missing)-added),error=self.error)
    def query_vector(self,query,fresh=False):
        if not self.config.semantic:return None
        old=None if fresh else self.get(query)
        if old is not None:return old
        if not self.provider:return None
        try:
            v=self.provider.embed([query])[0]
            count=self.store.db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0]
            if count<self.config.vector_budget_bytes//4096:self.save(query,v)
            return v
        except Exception as exc:self.error=type(exc).__name__+': '+str(exc)[:150];return None
    def candidates(self,query,units,qvec,round_no=1,requests=None):
        if not units:return set(),dict(round=round_no,paths={},candidates=0)
        limit=min(self.config.path_limit*round_no,64);lex=[];base=[];facets=[];events=[]
        qgrams=grams(query);docs=[grams(u.get('candidate_text',' '.join(f['quote'] for f in u['facts']))) for u in units];df=collections.Counter(g for doc in docs for g in doc)
        for u,doc in zip(units,docs):
            ls=sum(math.log(1+(len(units)-df[g]+.5)/(df[g]+.5)) for g in qgrams&doc)
            if ls:lex.append((ls,u['id']))
            ts=texts_for(u,self.config.view_cap);vs=[self.get(t) for t in ts] if qvec is not None else []
            if vs and vs[0] is not None:base.append((float(qvec@vs[0]),u['id']))
            extra=[float(qvec@v) for v in vs[1:] if v is not None]
            if extra:facets.append((max(extra),u['id']))
            event=u.get('event_key','')
            if event and canonical_event(event) in re.sub(r'[\W_的]+','',query):events.append((len(event),u['id']))
        paths={'text':lex,'base_semantic':base,'facet_semantic':facets,'event':events};scores={};sizes={}
        if requests:
            from .atoms import frame_compatible
            for req in requests:
                matching=[(lexical(query,u.get('candidate_text',' '.join(f['quote'] for f in u['facts']))),u['id']) for u in units if any(frame_compatible(f,req) for f in u['facts'])]
                paths['request:'+req['id']]=matching
        for name,items in paths.items():
            ordered=sorted(items,key=lambda x:(-x[0],x[1]))[:limit];sizes[name]=len(ordered)
            for rank,(_,uid) in enumerate(ordered):scores[uid]=scores.get(uid,0)+1/(61+rank)
        ids=[uid for uid,_ in sorted(scores.items(),key=lambda p:(-p[1],p[0]))[:self.config.candidate_limit]]
        return set(ids),dict(round=round_no,paths=sizes,candidates=len(ids),budget=self.config.candidate_limit,semantic_used=qvec is not None)
