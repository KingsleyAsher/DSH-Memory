"""Headless stdio MCP facade for the standalone tool-first prototype.

No network listener, UI, credential loading or implicit model inference.
"""
import argparse
import json
import sys
from .runtime import MemoryCore
from .tool_memory import ToolMemory


class NoInference:
    def call(self,*args,**kwargs):raise RuntimeError('explicit worker backend required')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--home',required=True)
    args=parser.parse_args()
    core=MemoryCore(args.home,model=NoInference());memory=ToolMemory(core)
    try:
        for line in sys.stdin.buffer:
            request=None
            try:
                request=json.loads(line);method=request.get('method');params=request.get('params',{})
                if 'id' not in request:continue
                if method=='initialize':
                    result=dict(protocolVersion=params.get('protocolVersion','2024-11-05'),capabilities=dict(tools={}),serverInfo=dict(name='standalone-memory',version='0.1.0'))
                elif method=='ping':result={}
                elif method=='tools/list':result=dict(tools=memory.tools())
                elif method=='tools/call':
                    try:
                        value=memory.dispatch(params['name'],params.get('arguments',{}))
                        result=dict(content=[dict(type='text',text=json.dumps(value,ensure_ascii=False))],isError=False)
                    except Exception as exc:result=dict(content=[dict(type='text',text=str(exc))],isError=True)
                else:raise ValueError('method not supported')
                response=dict(jsonrpc='2.0',id=request['id'],result=result)
            except Exception as exc:response=dict(jsonrpc='2.0',id=request.get('id') if isinstance(request,dict) else None,error=dict(code=-32603,message=str(exc)))
            sys.stdout.buffer.write((json.dumps(response,ensure_ascii=False)+'\n').encode('utf-8'));sys.stdout.buffer.flush()
    finally:core.close()


if __name__=='__main__':main()
