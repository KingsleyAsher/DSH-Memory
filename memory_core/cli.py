"""Local-only interface. It does not install hooks or contact DSH."""
import argparse,json,sys
from pathlib import Path
from .runtime import MemoryCore
from .policy import Config

def main():
    p=argparse.ArgumentParser(prog='memory_core');p.add_argument('--home',type=Path,required=True)
    s=p.add_subparsers(dest='command',required=True)
    init=s.add_parser('init');init.add_argument('--semantic',action='store_true');init.add_argument('--view-cap',type=int,choices=[1,2,3,4],default=4);init.add_argument('--extraction-mode',choices=['before_compact','immediate','token_threshold'],default='token_threshold');init.add_argument('--threshold-tokens',type=int,default=256000)
    add=s.add_parser('ingest');add.add_argument('input',type=Path);mode=add.add_mutually_exclusive_group();mode.add_argument('--defer',action='store_true');mode.add_argument('--immediate',action='store_true')
    for name in ['before-compact','before-reset','session-end']:
        event=s.add_parser(name);event.add_argument('--session-id',default='default')
    for name in ['threshold-status','run-threshold']:
        event=s.add_parser(name);event.add_argument('--session-id',default='default')
    prepare=s.add_parser('prepare-compaction');prepare.add_argument('--session-id',default='default')
    commit=s.add_parser('commit-compaction');commit.add_argument('batch_id');commit.add_argument('input',type=Path)
    abort=s.add_parser('abort-compaction');abort.add_argument('batch_id')
    q=s.add_parser('query');q.add_argument('text');q.add_argument('--project');q.add_argument('--entity');q.add_argument('--project-id');q.add_argument('--entity-id');q.add_argument('--event');q.add_argument('--at',type=int);q.add_argument('--evidence-only',action='store_true')
    run=s.add_parser('run');run.add_argument('--retry-failed',action='store_true')
    for name in ['exclude','include','delete']:
        x=s.add_parser(name);x.add_argument('source_id')
    r=s.add_parser('revise');r.add_argument('source_id');r.add_argument('text')
    s.add_parser('status');s.add_parser('history')
    export=s.add_parser('export');export.add_argument('output',type=Path)
    serve=s.add_parser('serve');serve.add_argument('--port',type=int,default=18651)
    a=p.parse_args()
    if a.command=='serve':
        from .server import serve as start
        start(a.home,a.port);return
    cfg=Config(semantic=a.semantic,view_cap=a.view_cap,extraction_mode=a.extraction_mode,extraction_threshold_tokens=a.threshold_tokens) if a.command=='init' else None
    core=MemoryCore(a.home,cfg)
    try:
        if a.command=='init':out=core.status()
        elif a.command=='ingest':
            if a.input.suffix.lower()=='.jsonl':rows=[json.loads(line) for line in a.input.read_text(encoding='utf-8').splitlines() if line.strip()]
            else:
                rows=json.loads(a.input.read_text(encoding='utf-8'));rows=rows if isinstance(rows,list) else [rows]
            out=[core.ingest(row,process=True if a.immediate else False if a.defer else None) for row in rows]
        elif a.command in ['before-compact','before-reset','session-end']:out=getattr(core,a.command.replace('-','_'))(a.session_id)
        elif a.command in ['threshold-status','run-threshold']:out=getattr(core,a.command.replace('-','_'))(a.session_id)
        elif a.command=='prepare-compaction':out=core.prepare_compaction(a.session_id)
        elif a.command=='commit-compaction':
            body=json.loads(a.input.read_text(encoding='utf-8'));out=core.commit_compaction(a.batch_id,body['value'],usage=body.get('usage'))
        elif a.command=='abort-compaction':core.abort_compaction(a.batch_id);out=core.status()
        elif a.command=='query':out=core.query(a.text,project=a.project,entity=a.entity,project_id=a.project_id,entity_id=a.entity_id,event=a.event,at=a.at,answer=not a.evidence_only)
        elif a.command=='run':out=core.run_pending(retry_failed=a.retry_failed)
        elif a.command in ['exclude','include']:core.exclude(a.source_id,a.command=='exclude');out=core.status()
        elif a.command=='delete':core.delete(a.source_id);out=core.status()
        elif a.command=='revise':out=core.revise(a.source_id,a.text)
        elif a.command=='history':out=dict(sources=core.store.sources(),facts=core.store.facts())
        elif a.command=='export':
            data=dict(config=core.config.to_dict(),sources=core.store.sources(),facts=core.store.facts())
            a.output.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');out=dict(output=str(a.output.resolve()),records=len(data['facts']))
        else:out=core.status()
        print(json.dumps(out,ensure_ascii=False,indent=2))
    finally:core.close()
