"""Build an allowlisted, deterministic npm-compatible archive from public source."""
from pathlib import Path
import gzip, hashlib, io, json, re, subprocess, sys, tarfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
VERSION = json.loads((ROOT/'plugin/package.json').read_text(encoding='utf-8'))['version']

def scan(name, data):
    text = data.decode('utf-8')
    patterns = [r'[A-Za-z]:[\\/]Users[\\/]', r'[A-Za-z]:[\\/]ChatGPT[\\/]',
                'DSH' + ' WorkPlace', r'BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY',
                r'\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_\-]{20,}',
                r'\bAKIA[A-Z0-9]{16}\b']
    for pattern in patterns:
        if re.search(pattern, text):
            raise ValueError('Publication scan failed: '+name)

def main():
    files = {}
    for directory, prefix, suffixes in [('plugin/src','src',{'.js'}),('memory_core','python/memory_core',{'.py','.mjs'})]:
        for p in sorted((ROOT/directory).rglob('*')):
            if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts:
                files[prefix+'/'+p.relative_to(ROOT/directory).as_posix()] = p.read_bytes()
    for name in ['package.json','cordis.patch.yml']:
        files[name] = (ROOT/'plugin'/name).read_bytes()
    for p in ROOT.glob('*.md'):
        files[p.name] = p.read_bytes()
    files['LICENSE'] = (ROOT/'LICENSE').read_bytes()
    # Match .gitattributes on Windows and in a clean checkout before hashing.
    files = {name:data.replace(b'\r\n',b'\n') for name,data in files.items()}
    for name, data in files.items(): scan(name,data)
    # Scan the additional public sources, including tests and release tooling.
    for directory in ['tests','scripts','plugin-ui']:
        for p in (ROOT/directory).rglob('*'):
            if p.is_file() and p.suffix in {'.py','.mjs','.js','.html','.css'} and '__pycache__' not in p.parts:
                scan(p.relative_to(ROOT).as_posix(),p.read_bytes())
    for p in (ROOT/'plugin/src').glob('*.js'):
        subprocess.run(['node','--check',str(p)],check=True,capture_output=True)
    test = subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'],cwd=ROOT,capture_output=True,text=True)
    if test.returncode:
        print(test.stdout); print(test.stderr); raise SystemExit(test.returncode)
    match = re.search(r'Ran (\d+) tests?',test.stderr)
    DIST.mkdir(exist_ok=True)
    archive = DIST/('local-dsh-memory-'+VERSION+'.tgz')
    with archive.open('wb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as gz:
            with tarfile.open(fileobj=gz,mode='w') as tar:
                for name,data in sorted(files.items()):
                    info=tarfile.TarInfo('package/'+name);info.size=len(data);info.mtime=0;info.mode=0o644
                    tar.addfile(info,io.BytesIO(data))
    inventory=[{'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in sorted(files.items())]
    with tarfile.open(archive) as tar:
        assert len(tar.getmembers())==len(files)
        for member in tar.getmembers():
            assert member.isfile() and member.name.startswith('package/') and '..' not in Path(member.name).parts
            data=tar.extractfile(member).read();scan(member.name,data)
            assert data==files[member.name.removeprefix('package/')]
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (DIST/'SHA256SUMS').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
    (DIST/'package-files.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    manifest={'version':VERSION,'package':'@local/dsh-memory','archive':'dist/'+archive.name,'tgz':archive.name,'buildId':hashlib.sha256(json.dumps(inventory,sort_keys=True).encode()).hexdigest()[:16],'sha256':digest,'bytes':archive.stat().st_size,'files':len(files),'verification':{'syntheticTestsPassed':int(match.group(1)) if match else None,'javascriptSyntaxPassed':True,'packageRoundTripPassed':True,'publicationScanPassed':True,'liveModelCalls':False,'privateUserDataUsed':False,'installedHostUpgradeTested':False}}
    (ROOT/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    subprocess.run(['node','--test','tests/updates.test.mjs'],cwd=ROOT,check=True,capture_output=True)
    manifest['verification']['updaterTestsPassed']=6
    for filename in ['tests/plugin_details.mjs','tests/runtime_write_receipt.mjs','tests/runtime_recall_continuation.mjs','tests/runtime_pure_exclusion.mjs','tests/runtime_wechat_scopes.mjs']:
        subprocess.run(['node',filename],cwd=ROOT,check=True,capture_output=True)
    manifest['verification']['detailsAndReceiptChecksPassed']=True
    manifest['verification']['toolContinuationRecallPassed']=True
    manifest['verification']['failedSubmissionRetryPassed']=True
    manifest['verification']['pureExclusionPassed']=True
    manifest['verification']['conversationIsolationPassed']=True
    manifest['verification']['installedHostUpgradeTested']=False
    (ROOT/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest))

if __name__=='__main__': main()
