-- Destructive central-image ledger fixture for a fresh disposable PostgreSQL
-- database only. Never execute this against the live control plane.
\set ON_ERROR_STOP on

SELECT encode(digest(convert_to('CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC','UTF8'),'sha256'),'hex') AS token_hash \gset

SET ROLE admira_provisioner;
SELECT tenant_id AS image_tenant
FROM admira.issue_telegram_tenant_claim(
  'image-cycle-001', 'Image Cycle', :'token_hash', 1800
) \gset
RESET ROLE;

SET ROLE admira_ingress;
SELECT tenant_id
FROM admira.claim_telegram_tenant(
  '123456', '92001', '92001', 'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC'
);
RESET ROLE;

-- First claim owns a fenced lease and a successful completion is replayed
-- without issuing another lease or provider attempt.
SET ROLE admira_image;
SELECT route AS first_route, status AS first_status, attempt_count AS first_attempt,
       job_id AS first_job, lease_token AS first_lease
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '11111111-1111-4111-8111-111111111111'::uuid, 3, 300
) \gset
SELECT admira.complete_central_image_job(
  :'first_job'::uuid, :'first_lease'::uuid,
  repeat('a', 32) || '.png', repeat('b', 64), 42, 'image/png'
) AS first_completed;
CREATE TEMP TABLE first_replay_snapshot AS
SELECT route, status, lease_token, output_ref, output_sha256, output_size_bytes
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '11111111-1111-4111-8111-111111111111'::uuid, 3, 300
);
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM first_replay_snapshot
    WHERE route = 'central_sponsored' AND status = 'succeeded'
      AND lease_token IS NULL AND output_ref = repeat('a', 32) || '.png'
      AND output_sha256 = repeat('b', 64) AND output_size_bytes = 42
  ) OR NOT EXISTS (
    SELECT 1 FROM admira.central_image_jobs
    WHERE tenant_id = (SELECT id FROM admira.tenants WHERE external_customer_id = 'image-cycle-001')
      AND request_id = '11111111-1111-4111-8111-111111111111'::uuid
      AND status = 'succeeded' AND attempt_count = 1
  ) THEN
    RAISE EXCEPTION 'durable image success was not idempotent';
  END IF;
END;
$$;

-- A licensed tenant whose explicit central-pool switch is off stays active,
-- but the runtime-keyed boundary returns personal_chatgpt and creates no job.
SET ROLE admira_provisioner;
SELECT * FROM admira.transition_hosted_tenant_to_licensed(
  'image-cycle-001', 'ADMIRA-IMAGE-LICENSE-001',
  'tenant-env://image-cycle-001/GEMINI_API_KEY', repeat('c', 64),
  'central-image-fixture'
);
RESET ROLE;
UPDATE admira.tenant_entitlements
SET image_sponsorship_ends_at = now() - interval '1 second'
WHERE tenant_id = :'image_tenant'::uuid;

SET ROLE admira_image;
CREATE TEMP TABLE personal_route_snapshot AS
SELECT route, status
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '22222222-2222-4222-8222-222222222222'::uuid, 3, 300
);
RESET ROLE;

UPDATE admira.tenant_entitlements
SET image_sponsorship_ends_at = now() + interval '1 day'
WHERE tenant_id = :'image_tenant'::uuid;

-- The timestamp above is intentionally insufficient for a licensed tenant.
-- Only the narrow operator switch admits the shared central image pool.
SET ROLE admira_operator;
SELECT route AS central_pool_route
FROM admira.operator_set_licensed_central_image_pool('image-cycle-001', true) \gset
RESET ROLE;

-- An expired lease can be reclaimed. The former token is fenced and only the
-- new token can complete the exact request.
SET ROLE admira_image;
SELECT job_id AS crash_job, lease_token AS stale_lease
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '33333333-3333-4333-8333-333333333333'::uuid, 3, 300
) \gset
RESET ROLE;
UPDATE admira.central_image_jobs SET leased_until = now() - interval '1 second'
WHERE id = :'crash_job'::uuid;
SET ROLE admira_image;
SELECT status AS reclaimed_status, attempt_count AS reclaimed_attempt,
       lease_token AS current_lease
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '33333333-3333-4333-8333-333333333333'::uuid, 3, 300
) \gset
SELECT admira.complete_central_image_job(
  :'crash_job'::uuid, :'stale_lease'::uuid,
  repeat('f', 32) || '.jpg', repeat('f', 64), 43, 'image/jpeg'
) AS stale_completed;
SELECT admira.complete_central_image_job(
  :'crash_job'::uuid, :'current_lease'::uuid,
  repeat('d', 32) || '.jpg', repeat('e', 64), 43, 'image/jpeg'
) AS reclaimed_completed;
RESET ROLE;

-- Retry delay is durable: an immediate retry sees queued without a lease.
SET ROLE admira_image;
SELECT job_id AS retry_job, lease_token AS retry_lease
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '44444444-4444-4444-8444-444444444444'::uuid, 3, 300
) \gset
SELECT status AS failed_status
FROM admira.fail_central_image_job(
  :'retry_job'::uuid, :'retry_lease'::uuid, 'provider_failed', 300
);
CREATE TEMP TABLE delayed_retry_snapshot AS
SELECT status, lease_token
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '44444444-4444-4444-8444-444444444444'::uuid, 3, 300
);
RESET ROLE;

-- With one allowed attempt, an expired running lease becomes terminal.
SET ROLE admira_image;
SELECT job_id AS terminal_job
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '55555555-5555-4555-8555-555555555555'::uuid, 1, 300
) \gset
RESET ROLE;
UPDATE admira.central_image_jobs SET leased_until = now() - interval '1 second'
WHERE id = :'terminal_job'::uuid;
SET ROLE admira_image;
CREATE TEMP TABLE terminal_snapshot AS
SELECT status, error_code, lease_token
FROM admira.begin_central_image_job_for_runtime(
  'image-cycle-001', '55555555-5555-4555-8555-555555555555'::uuid, 1, 300
);
RESET ROLE;

DO $$
BEGIN
  IF NOT EXISTS (
       SELECT 1 FROM personal_route_snapshot
       WHERE route = 'personal_chatgpt' AND status IS NULL
     ) OR NOT EXISTS (
       SELECT 1 FROM admira.central_image_jobs
       WHERE request_id = '33333333-3333-4333-8333-333333333333'::uuid
         AND status = 'succeeded' AND attempt_count = 2
         AND output_ref = repeat('d', 32) || '.jpg'
     ) OR NOT EXISTS (
       SELECT 1 FROM delayed_retry_snapshot
       WHERE status = 'queued' AND lease_token IS NULL
     ) OR NOT EXISTS (
       SELECT 1 FROM terminal_snapshot
       WHERE status = 'failed' AND error_code = 'lease_expired' AND lease_token IS NULL
     ) THEN
    RAISE EXCEPTION 'central image lease, backoff or entitlement fencing failed';
  END IF;
  IF (SELECT count(*) FROM admira.central_image_jobs) <> 4 THEN
    RAISE EXCEPTION 'blocked image route created a durable job';
  END IF;
  IF has_table_privilege('admira_image', 'admira.central_image_jobs', 'SELECT')
     OR NOT has_function_privilege(
       'admira_image',
       'admira.begin_central_image_job_for_runtime(text,uuid,integer,integer)',
       'EXECUTE'
     ) THEN
    RAISE EXCEPTION 'central image role privileges are not least privilege';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'admira' AND table_name = 'central_image_jobs'
      AND column_name ~ '(prompt|provider_response|secret|api_key)'
  ) THEN
    RAISE EXCEPTION 'central image ledger contains forbidden request/provider data';
  END IF;
END;
$$;

SELECT 'central_image_jobs_validation=passed';
