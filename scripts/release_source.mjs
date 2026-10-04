// Release credentials are confined to the existing GitHub environment.
const repo='jlboper/Crypto-BOT';
export function releaseSource(env){
  const sha=env.RELEASE_SHA||env.GITHUB_SHA;
  if(env.GITHUB_REPOSITORY!==repo||env.GITHUB_EVENT_NAME!=='push'||env.GITHUB_REF!=='refs/heads/main'
    ||!/^[a-f0-9]{40}$/.test(sha||'')||sha!==env.GITHUB_SHA
    ||(env.RELEASE_REF&&env.RELEASE_REF!==env.GITHUB_REF))throw Error('Validated main release source required');
  return sha;
}
export async function requireCurrentMain(env,transport=fetch){
  const sha=releaseSource(env);
  if(!env.GITHUB_TOKEN)throw Error('GitHub release identity unavailable');
  const response=await transport(`https://api.github.com/repos/${repo}/git/ref/heads/main`,{
    headers:{Authorization:`Bearer ${env.GITHUB_TOKEN}`,Accept:'application/vnd.github+json',
      'X-GitHub-Api-Version':'2022-11-28'},redirect:'error',signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw Error('Cannot verify current main release');
  let ref;
  try{ref=await response.json();}catch{throw Error('Cannot verify current main release');}
  if(ref?.object?.sha!==sha)throw Error('Release superseded by current main');
  return sha;
}
