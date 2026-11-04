"""Optional read-only adapter; never scans a personal knowledge directory."""
from typing import Protocol
class KnowledgeAdapter(Protocol):
    def search(self,query:str,project:str,entity:str,limit:int=2)->list[dict]:...

class StaticKnowledge:
    """Test/example provider supplied explicitly by the caller, no disk scan."""
    def __init__(self,records):self.records=list(records)
    def search(self,query,project,entity,limit=2):
        from .index import lexical
        rows=[r for r in self.records if r['project']==project and r['entity']==entity and not r.get('excluded')]
        return sorted(rows,key=lambda r:-lexical(query,r['quote']))[:limit]

def checked_search(adapter,query,project,entity):
    if adapter is None:return []
    result=[]
    rows=adapter.search(query,project,entity,limit=2)
    if not isinstance(rows,list) or len(rows)>2:raise ValueError('knowledge budget violation')
    for r in rows:
        required=['source_id','project','entity','quote','value_text','field','kind','epistemic']
        if any(k not in r for k in required) or r['project']!=project or r['entity']!=entity:raise ValueError('knowledge scope/provenance violation')
        if not r['quote'] or r['value_text'] not in r['quote'] or not r.get('version') or any(not isinstance(r[k],str) for k in required):raise ValueError('knowledge record requires quoted versioned source')
        result.append(r)
    return result
