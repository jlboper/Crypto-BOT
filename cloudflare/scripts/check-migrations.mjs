// Read-only preflight: never initialize or modify the migration table.
export async function checkMigrations({accountId,databaseId,token,expected,allowPending=[]},transport=fetch){
  const response=await transport(`https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`,{
    method:'POST',redirect:'error',signal:AbortSignal.timeout(15000),
    headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},
    body:JSON.stringify({sql:'SELECT name FROM d1_migrations ORDER BY id',params:[]})
  });
  if(!response.ok)throw Error('D1 migration verification failed');
  const data=await response.json();
  if(data.success!==true||!Array.isArray(data.result)||data.result.length!==1||data.result[0].success!==true||!Array.isArray(data.result[0].results))throw Error('Invalid D1 migration response');
  const applied=data.result[0].results.map(row=>row.name);
  if(applied.some(name=>typeof name!=='string')||new Set(applied).size!==applied.length)throw Error('Invalid D1 migration history');
  if(expected.some(name=>!applied.includes(name)&&!allowPending.includes(name)))throw Error('Pending D1 migration; review and apply it separately before publication');
  if(applied.some(name=>!expected.includes(name)))throw Error('D1 schema is ahead of this release');
  return applied;
}
