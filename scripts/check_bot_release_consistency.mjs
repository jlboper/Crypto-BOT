// Fail before production approval when tracked bot files changed without a version bump.
import {readFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';

const origin='https://crypto-paper-private-portal.jlboper.workers.dev';
const sha=spawnSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).stdout.trim();
if(!/^[a-f0-9]{40}$/.test(sha))throw Error('Cannot resolve exact commit for release preflight');

const built=spawnSync('python',['scripts/build_bot_release.py','--commit',sha,'--sequence','1','--expires','2147483647','--output','dist/preflight-bot.zip'],{stdio:'inherit'});
if(built.status!==0)throw Error('Bot release preflight package build failed');
const manifest=JSON.parse(await readFile('dist/preflight-bot.manifest.json','utf8'));

const response=await fetch(origin+'/v1/releases/latest',{redirect:'error',signal:AbortSignal.timeout(30000)});
if(response.status===404){
  console.log('No prior bot release; version consistency preflight passed.');
  process.exit(0);
}
if(!response.ok)throw Error('Cannot verify latest bot release before production approval');
const previous=(await response.json()).manifest;
const parts=v=>{
  if(!/^\d+\.\d+\.\d+$/.test(v||''))throw Error('Invalid semantic version in release preflight');
  return v.split('.').map(Number);
};
const a=parts(manifest.version),b=parts(previous.version);
const comparison=a[0]-b[0]||a[1]-b[1]||a[2]-b[2];
const sameFiles=JSON.stringify(Object.entries(manifest.files).sort())===JSON.stringify(Object.entries(previous.files).sort());
if(comparison<0)throw Error(`Bot version downgrade blocked before production approval: ${manifest.version} < ${previous.version}`);
if(comparison===0&&!sameFiles)throw Error(`Bot package changed but version stayed at ${manifest.version}. Increment pyproject.toml before production approval.`);
if(comparison>0&&sameFiles)console.log(`Version ${manifest.version} is newer although bot files are unchanged; allowed.`);
else if(comparison>0)console.log(`Bot package changed with valid version increment: ${previous.version} -> ${manifest.version}.`);
else console.log(`Bot package is identical to already published version ${manifest.version}.`);
