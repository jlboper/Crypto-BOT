export const PASSWORD_ITERATIONS=600000;
export function validPassword(value){
  return typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
}
export async function passwordDigest(password,salt){
  // The browser stretches the password with the public per-password salt.
  // Store only a hash of that proof, never the reusable proof itself.
  const bits=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(password));
  return Array.from(new Uint8Array(bits),b=>b.toString(16).padStart(2,'0')).join('');
}
