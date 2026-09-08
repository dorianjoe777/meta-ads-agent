// Run against a deployed gateway; credentials are read from the environment
// and neither credentials nor session tokens are included in output.
import assert from 'node:assert/strict';

const base = process.env.OPERATOR_TEST_URL || 'https://dashboard.uboost.lat';
const password = process.env.OPERATOR_TEST_PASSWORD;
assert(password, 'Set OPERATOR_TEST_PASSWORD before running the smoke check');
let cookie;
let csrf;

async function request(path, options = {}, authenticated = true) {
  const response = await fetch(new URL('/api/operator/' + path, base), {
    ...options,
    headers: {
      'content-type': 'application/json',
      ...(authenticated && cookie ? { cookie } : {}),
      ...options.headers,
    },
    redirect: 'error',
    signal: AbortSignal.timeout(20000),
  });
  assert.match(response.headers.get('content-type') || '', /application\/json/, `${path}: expected API JSON, got HTTP ${response.status}`);
  const body = await response.json();
  return { response, body };
}

try {
  const login = await request('login', { method: 'POST', body: JSON.stringify({ password }) });
  assert.equal(login.response.status, 200, 'login failed');
  assert.equal(login.body.authenticated, true);
  cookie = login.response.headers.get('set-cookie')?.split(';', 1)[0];
  csrf = login.body.csrf_token;
  assert(cookie && csrf, 'Missing session cookie or CSRF token');
  const endpoints = [
    ['gemini/status', 'projects'],
    ['codex/status', 'accounts'],
    ['sponsorship/status', 'tenants'],
    ['trials', 'trials'],
    ['licensed', 'licensed'],
  ];
  const session = await request('session');
  assert.equal(session.body.authenticated, true);
  for (const [path, field] of endpoints) {
    const { response, body } = await request(path);
    assert.equal(response.status, 200, `${path}: request failed`);
    assert.equal(body.ok, true, `${path}: API error`);
    assert(Array.isArray(body[field]), `${path}: missing ${field}`);
    console.log(`PASS ${path}: ${body[field].length} records`);
  }
  // Three-level routes and nested POSTs must reach backend authentication;
  // no client record is modified by these unauthenticated requests.
  for (const [path, method] of [['codex/primary/status', 'GET'], ['trials/routing-smoke/extend', 'POST'], ['trials/routing-smoke/delete', 'POST']]) {
    const { response, body } = await request(path, {
      method, ...(method === 'POST' ? { body: '{}' } : {}),
    }, false);
    assert.equal(response.status, 401, `${path}: authentication must be required`);
    assert.equal(body.error_code, 'authentication_required');
    console.log(`PASS ${method} ${path}: authentication enforced`);
  }
} finally {
  if (cookie && csrf) {
    const logout = await request('logout', { method: 'POST', body: '{}', headers: { 'x-csrf-token': csrf } });
    assert.equal(logout.response.status, 200, 'logout failed');
    const session = await request('session');
    assert.equal(session.body.authenticated, false, 'session must be revoked');
  }
}
