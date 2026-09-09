import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../../deploy/contabo/operator_dashboard.js', import.meta.url), 'utf8');
const functions = [
  ['  async function refreshCustomers(', '  function setCustomerTab('],
  ['  function reconcileTrialCreation(', '  function clearClaim('],
].map(([start, end]) => source.slice(source.indexOf(start), source.indexOf(end))).join('\n');

function fixture() {
  const elements = new Map();
  const $ = (id) => {
    if (!elements.has(id)) elements.set(id, { textContent: '', value: '', setAttribute() {}, getAttribute() { return ''; } });
    return elements.get(id);
  };
  $('#trial-runtime-key').value = 'client-test';
  $('#trial-display-name').value = 'Client Test';
  const context = {
    $, state: { authenticated: true, sessionVersion: 1, trials: [], licensed: [], trialCreationIssue: null },
    notices: [], records: [], postError: { code: 'gemini_pool_health_check_failed' }, refreshError: false,
    setBusy() {}, setFormBusy() {}, renderCustomers() {}, validateForm() { return true; },
    invalidField() { throw Error('unexpected invalid field'); },
    messageFor(e, fallback) { return e.code || fallback; },
    setNotice(text, level) { context.notices.push({ text, level }); },
    async refreshGemini() {}, showClaim() {},
    async request(path, options) {
      if (options?.method === 'POST') throw context.postError;
      if (context.refreshError) throw { code: 'network_error' };
      return path.endsWith('/trials') ? { trials: context.records } : { licensed: [] };
    },
  };
  vm.createContext(context);
  vm.runInContext(functions, context);
  return context;
}

// Creation persists but verification fails; later Enlace/refresh recovers it.
const ctx = fixture();
ctx.records = [{ runtime_key: 'client-test', gemini_pool_ready: false, lifecycle_state: 'trial' }];
await ctx.createTrial({ preventDefault() {}, currentTarget: { getAttribute() { return ''; } } });
assert.match(ctx.$('#trial-error').textContent, /ya se creó/);
assert.match(ctx.$('#trial-error').textContent, /Pulsa Enlace/);
ctx.records[0].gemini_pool_ready = true;
await ctx.refreshCustomers();
assert.equal(ctx.$('#trial-error').textContent, '');
assert.equal(ctx.state.trialCreationIssue, null);
assert.equal(ctx.notices.at(-1).level, 'success');

// A lost response with confirmed readiness is reconciled immediately.
const ready = fixture();
ready.postError = { code: 'request_timeout' };
ready.records = [{ runtime_key: 'client-test', gemini_pool_ready: true, lifecycle_state: 'trial' }];
await ready.createTrial({ preventDefault() {}, currentTarget: { getAttribute() { return ''; } } });
assert.equal(ready.$('#trial-error').textContent, '');
assert.equal(ready.notices.at(-1).level, 'success');

// Another account or an unavailable refresh cannot turn an error into success.
for (const unavailable of [false, true]) {
  const failed = fixture();
  failed.records = [{ runtime_key: 'different-client', gemini_pool_ready: true, lifecycle_state: 'trial' }];
  failed.refreshError = unavailable;
  await failed.createTrial({ preventDefault() {}, currentTarget: { getAttribute() { return ''; } } });
  assert.match(failed.$('#trial-error').textContent, /gemini_pool_health_check_failed/);
  assert.equal(failed.notices.length, 0);
}
assert.equal(source, readFileSync(new URL('../public/operator_dashboard.js', import.meta.url), 'utf8'));
console.log('PASS partial creation, recovered readiness, stale error cleanup, failed refresh and asset parity');
