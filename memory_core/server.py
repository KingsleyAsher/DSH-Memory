"""Explicit loopback-only HTTP server; never registers a startup service."""
import json
from http.server import BaseHTTPRequestHandler,HTTPServer
from .runtime import MemoryCore

def serve(home,port=18651):
    if not 1024<=int(port)<=65535:raise ValueError('invalid loopback port')
    core=MemoryCore(home)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,status,value):
            b=json.dumps(value,ensure_ascii=False).encode('utf-8');self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
        def do_GET(self):
            if self.path=='/health':self.respond(200,dict(ok=True,**core.status()))
            elif self.path=='/history':self.respond(200,dict(sources=core.store.sources(),facts=core.store.facts()))
            else:self.respond(404,dict(error='unknown route'))
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1024*1024:raise ValueError('invalid payload size')
                body=json.loads(self.rfile.read(length))
                if self.path=='/ingest':out=core.ingest(body['source'],process=body.get('process',False if body.get('defer') else None))
                elif self.path in ['/before-compact','/before-reset','/session-end']:out=getattr(core,self.path[1:].replace('-','_'))(body.get('session_id','default'),retry_failed=body.get('retry_failed',True))
                elif self.path=='/threshold-status':out=core.threshold_status(body.get('session_id','default'))
                elif self.path=='/run-threshold':out=core.run_threshold(body.get('session_id','default'),retry_failed=body.get('retry_failed',True))
                elif self.path=='/prepare-compaction':out=core.prepare_compaction(body.get('session_id','default'),retry_failed=body.get('retry_failed',True))
                elif self.path=='/commit-compaction':out=core.commit_compaction(body['batch_id'],body['value'],usage=body.get('usage'))
                elif self.path=='/abort-compaction':core.abort_compaction(body['batch_id']);out=core.status()
                elif self.path=='/query':out=core.query(body['text'],project=body.get('project'),entity=body.get('entity'),project_id=body.get('project_id'),entity_id=body.get('entity_id'),event=body.get('event'),at=body.get('at'),answer=body.get('answer',True))
                elif self.path=='/run':out=core.run_pending(retry_failed=body.get('retry_failed',False))
                elif self.path=='/exclude':core.exclude(body['id'],body.get('excluded',True));out=core.status()
                elif self.path=='/delete':core.delete(body['id']);out=core.status()
                elif self.path=='/revise':out=core.revise(body['id'],body['text'])
                else:self.respond(404,dict(error='unknown route'));return
                self.respond(200,out)
            except (ValueError,KeyError) as exc:self.respond(400,dict(error=str(exc)))
            except Exception as exc:self.respond(503,dict(error=type(exc).__name__,detail='local operation unavailable; no alternate model used'))
    server=HTTPServer(('127.0.0.1',int(port)),Handler)
    try:server.serve_forever()
    finally:server.server_close();core.close()
