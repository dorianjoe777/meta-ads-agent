// Explicitly creates and deletes only a new, random disposable trial.
// Never pass an existing customer key to this check.
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';

assert.equal(process.env.OPERATOR_DELETE_SMOKE, '1', 'Set OPERATOR_DELETE_SMOKE=1 to create a disposable trial');
const base = process.env.OPERATOR_TEST_URL || 'https://dashboard.uboost.lat';
const password = process.env.OPERATOR_TEST_PASSWORD;
assert(password, 'Set OPERATOR_TEST_PASSWORD');
const key = 'delete-smoke-' + randomBytes(6).toString('hex');
let cookie, csrf, fixture, created = false;

async function request(path, body, useCsrf = true) {
  const response = await fetch(new URL('/api/operator/' + path, base), {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'content-type': 'application/json', ...(cookie ? { cookie } : {}),
      ...(csrf && useCsrf ? { 'x-csrf-token': csrf } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(60000), redirect: 'error',
  });
  assert.match(response.headers.get('content-type') || '', /application\/json/);
  const data = await response.json();
  return { status: response.status, data, response };
}
async function read(path) {
  const result = await request(path);
  assert.equal(result.status, 200, path);
  assert.equal(result.data.ok, true, path);
  return result.data;
}
const poolSnapshot = (data) => data.projects.map(({ project_ref, capacity, used, available }) =>
  ({ project_ref, capacity, used, available })).sort((a,b) => a.project_ref.localeCompare(b.project_ref));

try {
  const login = await request('login', { password });
  assert.equal(login.status, 200);
  cookie = login.response.headers.get('set-cookie')?.split(';', 1)[0];
  csrf = login.data.csrf_token;
  assert(cookie && csrf);
  const before = (await read('trials')).trials;
  const poolBefore = poolSnapshot(await read('gemini/status'));
  assert(!before.some((item) => item.runtime_key === key));
  const result = await request('trials', { runtime_key: key, display_name: 'Disposable deletion check' });
  // Even failed provisioning can leave this newly generated fixture behind.
  fixture = (await read('trials')).trials.find((item) => item.runtime_key === key);
  created = Boolean(fixture);
  assert.equal(result.status, 200, 'disposable trial creation failed');
  assert(fixture?.gemini_pool_ready, 'fixture must have a Gemini assignment');
  const occupied = poolSnapshot(await read('gemini/status'));
  assert.equal(occupied.reduce((n,p) => n+p.used, 0), poolBefore.reduce((n,p) => n+p.used, 0)+1);
  const payload = { confirmation: key, tenant_created_at: fixture.tenant_created_at };
  assert.equal((await request('trials/' + key + '/delete', payload, false)).status, 403);
  assert.equal((await request('trials/' + key + '/delete', { ...payload, confirmation: 'wrong' })).status, 400);
  assert.equal((await request('trials/' + key + '/delete', { ...payload, tenant_created_at: '2000-01-01T00:00:00Z' })).status, 409);
  assert((await read('trials')).trials.some((item) => item.runtime_key === key));
  const deleted = await request('trials/' + key + '/delete', payload);
  assert.equal(deleted.status, 200, 'workspace cleanup failed: ' + (deleted.data.error_code || 'unknown'));
  assert.equal(deleted.data.deleted, true);
  created = false;
  assert.equal((await request('trials/' + key + '/delete', payload)).status, 200, 'retry must be idempotent');
  const after = (await read('trials')).trials;
  assert.deepEqual(after.map(x => x.runtime_key).sort(), before.map(x => x.runtime_key).sort());
  assert.deepEqual(poolSnapshot(await read('gemini/status')), poolBefore, 'pool capacity must be restored');
  console.log('PASS permanent deletion, confirmation, CSRF, stale identity, retry and pool preservation');
  console.log('Disposable fixture removed: ' + key);
} finally {
  try {
    if (created && fixture) {
      const cleanup = await request('trials/' + key + '/delete', {
        confirmation: key, tenant_created_at: fixture.tenant_created_at,
      });
      assert.equal(cleanup.status, 200, 'Disposable fixture needs cleanup: ' + key);
    }
  } finally {
    if (cookie && csrf) await request('logout', {});
  }
}
