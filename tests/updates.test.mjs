import test from 'node:test';
import assert from 'node:assert/strict';
import {createUpdateChecker,compareReleaseVersions,verifyUpdateArchive} from '../plugin/src/updates.js';
import {readFile} from 'node:fs/promises';
const stable=version=>({package:'@local/dsh-memory',version,tgz:`local-dsh-memory-${version}.tgz`,sha256:'a'.repeat(64),bytes:123,buildId:'b'.repeat(16)});
const checker=(current,version,preview)=>createUpdateChecker({currentVersion:current,fetch:async url=>Response.json(url.includes('preview-manifest')?(preview||{package:'@local/dsh-memory',channel:'preview',active:false}):stable(version))});
test('numeric versions and stable versus preview ordering',()=>{
 assert.ok(compareReleaseVersions('1.10.0','1.9.9')>0);
 assert.ok(compareReleaseVersions('1.1.0','1.1-beta99')>0);
 assert.ok(compareReleaseVersions('1.1-beta10','1.1-beta2')>0);
});
test('all newer versions install automatically, including preview and major upgrades',async()=>{
 assert.equal((await checker('1.0.0','1.0.1').check()).autoInstallEligible,true);
 assert.equal((await checker('1.0.0','2.0.0').check()).autoInstallEligible,true);
 assert.equal((await checker('1.0-beta1','1.0.1').check()).autoInstallEligible,true);
 assert.equal((await checker('1.0.1','1.0.0').check()).updateAvailable,false);
 const result=await checker('1.0.0','1.0.1',stable('1.1-beta1')).check();
 assert.equal(result.preview.autoInstallEligible,true);assert.equal(result.preview.updateAvailable,true);
 assert.equal(result.latestVersion,'1.1-beta1');assert.equal(result.autoInstallEligible,true);
 const newerStable=await checker('1.0-beta1','2.0.0',stable('1.1-beta1')).check();assert.equal(newerStable.latestVersion,'2.0.0');
 const fallback=await createUpdateChecker({currentVersion:'1.0.0',fetch:async url=>{if(!url.includes('preview-manifest'))throw Error('offline');return Response.json(stable('1.1-beta1'))}}).check();
 assert.equal(fallback.latestVersion,'1.1-beta1');assert.equal(fallback.autoInstallEligible,true);
});
test('failure does not report current version as latest',async()=>{
 const result=await createUpdateChecker({currentVersion:'1.0.1',fetch:async()=>{throw Error('offline')}}).check();
 assert.equal(result.ok,false);assert.equal(result.autoInstallEligible,undefined);
});
test('distributed archive verifies and corruption is rejected',async()=>{
 const m=JSON.parse(await readFile(new URL('../release-manifest.json',import.meta.url)));
 const raw=await readFile(new URL('../'+m.archive,import.meta.url));
 assert.equal(verifyUpdateArchive(raw,{...m,latestVersion:m.version}).version,m.version);
 const broken=Buffer.from(raw);broken[20]^=1;
 assert.throws(()=>verifyUpdateArchive(broken,{...m,latestVersion:m.version}));
});
