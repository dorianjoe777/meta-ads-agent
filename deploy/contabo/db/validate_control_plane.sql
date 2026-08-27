-- Destructive fixture for a disposable PostgreSQL database only. The script
-- exercises every least-privilege service boundary without external APIs.
\set ON_ERROR_STOP on

SELECT encode(digest(convert_to('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA','UTF8'),'sha256'),'hex') AS token_hash \gset
SET ROLE admira_provisioner;
SELECT tenant_id AS issued_tenant
FROM admira.issue_telegram_tenant_claim('buyer-001','Buyer One', :'token_hash', 1800) \gset
RESET ROLE;

SET ROLE admira_ingress;
SELECT tenant_id AS claimed_tenant
FROM admira.claim_telegram_tenant('123456','9001','9001','AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA') \gset
SELECT tenant_id AS resolved_tenant FROM admira.resolve_telegram_chat('123456','9001','9001') \gset
SELECT update_row_id, inserted
FROM admira.ingest_telegram_update('123456', 42, '9001', '9001',
  '{"message":"hola","media":[]}'::jsonb) \gset
RESET ROLE;
SELECT 'binding_matches=' || (:'issued_tenant' = :'claimed_tenant' AND :'claimed_tenant' = :'resolved_tenant');

SET ROLE admira_runtime;
SELECT update_row_id AS claimed_update, tenant_id AS update_tenant, lease_token AS update_lease
FROM admira.claim_telegram_updates('runtime-test', 1, 360) \gset
SELECT lease_token AS runtime_lease
FROM admira.acquire_runtime_lease(:'update_tenant', 'runtime-test', 900) WHERE acquired \gset
SELECT admira.sync_hermes_scheduled_jobs(
  :'update_tenant', :'runtime_lease', '123456', '9001',
  jsonb_build_array(jsonb_build_object(
    'id','daily-1','name','Daily','enabled',true,
    'next_run_at',(now() - interval '1 minute')::text,
    'schedule_display','daily','timezone','UTC')));
SELECT admira.complete_telegram_update(
  :'claimed_update', :'update_lease', 'Respuesta normal', '[]'::jsonb);
SELECT admira.release_runtime_lease(:'update_tenant', :'runtime_lease');
RESET ROLE;

SET ROLE admira_delivery;
SELECT outbox_id AS first_outbox, lease_token AS first_outbox_lease
FROM admira.claim_telegram_outbox('delivery-test', 20, 180) \gset
SELECT admira.ack_telegram_outbox(
  :'first_outbox', :'first_outbox_lease', true, 1001, NULL, 30, 8);
SELECT outbox_id AS second_outbox, lease_token AS second_outbox_lease
FROM admira.claim_telegram_outbox('delivery-test', 20, 180) \gset
SELECT admira.ack_telegram_outbox(
  :'second_outbox', :'second_outbox_lease', true, 1002, NULL, 30, 8);
RESET ROLE;

SET ROLE admira_scheduler;
SELECT job_id AS scheduler_job, tenant_id AS scheduler_tenant, run_id AS scheduler_run,
       lease_token AS scheduler_job_lease
FROM admira.claim_due_scheduled_jobs('scheduler-test', 1, 900) \gset
SELECT lease_token AS scheduler_runtime_lease
FROM admira.acquire_runtime_lease(:'scheduler_tenant','scheduler-test',1200)
WHERE acquired \gset
SELECT admira.complete_scheduled_job_run(
  :'scheduler_job', :'scheduler_run', :'scheduler_job_lease', NULL,
  'Lectura diaria', '[]'::jsonb, '{"runtime_ok":true}'::jsonb);
SELECT admira.release_runtime_lease(:'scheduler_tenant', :'scheduler_runtime_lease');
RESET ROLE;

SET ROLE admira_delivery;
SELECT outbox_id AS cron_outbox, lease_token AS cron_outbox_lease
FROM admira.claim_telegram_outbox('delivery-test', 20, 180) \gset
SELECT admira.ack_telegram_outbox(
  :'cron_outbox', :'cron_outbox_lease', true, 1003, NULL, 30, 8);
RESET ROLE;

SELECT 'updates=' || count(*) FROM admira.tenant_telegram_updates WHERE status='processed';
SELECT 'outbox_sent=' || count(*) FROM admira.tenant_telegram_outbox WHERE status='sent';
SELECT 'cron_succeeded=' || count(*) FROM admira.tenant_scheduled_job_runs WHERE status='succeeded';
SELECT 'raw_claim_persisted=' || count(*)
FROM admira.tenant_telegram_claims WHERE encode(token_hash,'escape') LIKE '%AAAA%';
SELECT 'least_privilege=' || bool_and(
  NOT has_table_privilege(role_name, 'admira.tenant_telegram_updates', 'SELECT'))
FROM (VALUES ('admira_ingress'),('admira_runtime'),('admira_delivery'),
             ('admira_scheduler'),('admira_provisioner')) AS roles(role_name);
