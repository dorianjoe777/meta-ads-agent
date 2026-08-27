-- Admira Contabo multi-tenant foundation (PostgreSQL 15+)
--
-- This migration is intentionally forward-only and idempotent.  It owns only
-- control-plane state; Hermes workspaces and media remain in per-tenant
-- persistent volumes/object storage.  Run it in a transaction as a privileged
-- migration role, then grant the application role only the required privileges.
--
-- RLS is fail-closed: application queries see rows only when the transaction
-- has set LOCAL admira.tenant_id to the tenant UUID.  An unset/empty setting
-- matches no row.  The API must set it after authenticating the request and
-- must use SET LOCAL, never a process-global SET.

BEGIN;

CREATE SCHEMA IF NOT EXISTS admira;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION admira.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS admira.tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_customer_id text UNIQUE,
  display_name text NOT NULL CHECK (btrim(display_name) <> ''),
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'suspended', 'deleted')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS admira.tenant_telegram_bindings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  telegram_user_id text NOT NULL CHECK (btrim(telegram_user_id) <> ''),
  telegram_chat_id text NOT NULL CHECK (btrim(telegram_chat_id) <> ''),
  bot_id text NOT NULL CHECK (btrim(bot_id) <> ''),
  is_primary boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, telegram_chat_id),
  UNIQUE (bot_id, telegram_chat_id)
);

-- Durable Telegram inbox deduplication.  update_id is scoped by bot in the
-- Telegram API, so the pair is the idempotency key.  The tenant FK prevents an
-- update from being attached to another tenant's binding/workspace.
CREATE TABLE IF NOT EXISTS admira.tenant_telegram_updates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  bot_id text NOT NULL CHECK (btrim(bot_id) <> ''),
  update_id bigint NOT NULL CHECK (update_id >= 0),
  received_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  status text NOT NULL DEFAULT 'received'
    CHECK (status IN ('received', 'processing', 'processed', 'failed')),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  error text,
  UNIQUE (bot_id, update_id),
  UNIQUE (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS admira.tenant_entitlements (
  tenant_id uuid PRIMARY KEY REFERENCES admira.tenants(id) ON DELETE CASCADE,
  license_id text UNIQUE,
  plan text NOT NULL DEFAULT 'trial'
    CHECK (plan IN ('trial', 'paid', 'suspended', 'cancelled')),
  trial_started_at timestamptz,
  trial_ends_at timestamptz,
  paid_through timestamptz,
  hosting_until timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (trial_ends_at IS NULL OR trial_started_at IS NULL OR trial_ends_at >= trial_started_at)
);

CREATE TABLE IF NOT EXISTS admira.tenant_runtime_leases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL UNIQUE REFERENCES admira.tenants(id) ON DELETE CASCADE,
  runtime_key text NOT NULL UNIQUE CHECK (btrim(runtime_key) <> ''),
  state text NOT NULL DEFAULT 'stopped'
    CHECK (state IN ('starting', 'running', 'stopping', 'stopped', 'failed')),
  lease_token uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  holder text,
  acquired_at timestamptz,
  expires_at timestamptz,
  last_heartbeat_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at IS NULL OR acquired_at IS NULL OR expires_at >= acquired_at)
);

CREATE TABLE IF NOT EXISTS admira.tenant_scheduled_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  job_key text NOT NULL CHECK (btrim(job_key) <> ''),
  job_type text NOT NULL CHECK (btrim(job_type) <> ''),
  cron_expression text,
  timezone text NOT NULL DEFAULT 'UTC',
  enabled boolean NOT NULL DEFAULT true,
  next_run_at timestamptz,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, job_key)
);

CREATE TABLE IF NOT EXISTS admira.tenant_scheduled_job_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  job_id uuid NOT NULL,
  run_key text NOT NULL CHECK (btrim(run_key) <> ''),
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  scheduled_for timestamptz NOT NULL,
  started_at timestamptz,
  finished_at timestamptz,
  error text,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, job_id, run_key),
  CONSTRAINT scheduled_job_runs_job_same_tenant_fk
    FOREIGN KEY (tenant_id, job_id)
    REFERENCES admira.tenant_scheduled_jobs (tenant_id, id)
    ON DELETE CASCADE,
  CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS admira.tenant_audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES admira.tenants(id) ON DELETE CASCADE,
  actor_type text NOT NULL CHECK (btrim(actor_type) <> ''),
  actor_id text,
  event_type text NOT NULL CHECK (btrim(event_type) <> ''),
  resource_type text,
  resource_id text,
  request_id text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- The composite FK above needs the referenced pair to be unique.  This is
-- separate from the tenant-local job key so job IDs can still be opaque.
CREATE UNIQUE INDEX IF NOT EXISTS tenant_scheduled_jobs_tenant_id_id_uq
  ON admira.tenant_scheduled_jobs (tenant_id, id);

CREATE INDEX IF NOT EXISTS tenant_telegram_bindings_tenant_idx
  ON admira.tenant_telegram_bindings (tenant_id);
CREATE INDEX IF NOT EXISTS tenant_telegram_updates_tenant_received_idx
  ON admira.tenant_telegram_updates (tenant_id, received_at DESC);
CREATE INDEX IF NOT EXISTS tenant_telegram_updates_processing_idx
  ON admira.tenant_telegram_updates (status, received_at)
  WHERE status IN ('received', 'processing');
CREATE INDEX IF NOT EXISTS tenant_entitlements_plan_idx
  ON admira.tenant_entitlements (plan, paid_through);
CREATE INDEX IF NOT EXISTS tenant_runtime_leases_state_expiry_idx
  ON admira.tenant_runtime_leases (state, expires_at);
CREATE INDEX IF NOT EXISTS tenant_scheduled_jobs_due_idx
  ON admira.tenant_scheduled_jobs (enabled, next_run_at)
  WHERE enabled;
CREATE INDEX IF NOT EXISTS tenant_scheduled_job_runs_lookup_idx
  ON admira.tenant_scheduled_job_runs (tenant_id, job_id, scheduled_for DESC);
CREATE INDEX IF NOT EXISTS tenant_audit_events_tenant_created_idx
  ON admira.tenant_audit_events (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS tenant_audit_events_request_idx
  ON admira.tenant_audit_events (tenant_id, request_id)
  WHERE request_id IS NOT NULL;

DROP TRIGGER IF EXISTS tenants_touch_updated_at ON admira.tenants;
CREATE TRIGGER tenants_touch_updated_at
  BEFORE UPDATE ON admira.tenants
  FOR EACH ROW EXECUTE FUNCTION admira.touch_updated_at();
DROP TRIGGER IF EXISTS tenant_telegram_bindings_touch_updated_at ON admira.tenant_telegram_bindings;
CREATE TRIGGER tenant_telegram_bindings_touch_updated_at
  BEFORE UPDATE ON admira.tenant_telegram_bindings
  FOR EACH ROW EXECUTE FUNCTION admira.touch_updated_at();
DROP TRIGGER IF EXISTS tenant_entitlements_touch_updated_at ON admira.tenant_entitlements;
CREATE TRIGGER tenant_entitlements_touch_updated_at
  BEFORE UPDATE ON admira.tenant_entitlements
  FOR EACH ROW EXECUTE FUNCTION admira.touch_updated_at();
DROP TRIGGER IF EXISTS tenant_runtime_leases_touch_updated_at ON admira.tenant_runtime_leases;
CREATE TRIGGER tenant_runtime_leases_touch_updated_at
  BEFORE UPDATE ON admira.tenant_runtime_leases
  FOR EACH ROW EXECUTE FUNCTION admira.touch_updated_at();
DROP TRIGGER IF EXISTS tenant_scheduled_jobs_touch_updated_at ON admira.tenant_scheduled_jobs;
CREATE TRIGGER tenant_scheduled_jobs_touch_updated_at
  BEFORE UPDATE ON admira.tenant_scheduled_jobs
  FOR EACH ROW EXECUTE FUNCTION admira.touch_updated_at();

-- Explicitly enable and force RLS on every table carrying tenant_id.
DO $$
DECLARE
  table_name text;
BEGIN
  EXECUTE 'ALTER TABLE admira.tenants ENABLE ROW LEVEL SECURITY';
  EXECUTE 'ALTER TABLE admira.tenants FORCE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS tenant_isolation ON admira.tenants';
  EXECUTE 'CREATE POLICY tenant_isolation ON admira.tenants USING (id::text = NULLIF(current_setting(''admira.tenant_id'', true), '''')) WITH CHECK (id::text = NULLIF(current_setting(''admira.tenant_id'', true), ''''))';

  FOREACH table_name IN ARRAY ARRAY[
    'tenant_telegram_bindings', 'tenant_telegram_updates', 'tenant_entitlements',
    'tenant_runtime_leases', 'tenant_scheduled_jobs',
    'tenant_scheduled_job_runs', 'tenant_audit_events'
  ] LOOP
    EXECUTE format('ALTER TABLE admira.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE admira.%I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON admira.%I', table_name);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON admira.%I USING (tenant_id::text = NULLIF(current_setting(''admira.tenant_id'', true), '''')) WITH CHECK (tenant_id::text = NULLIF(current_setting(''admira.tenant_id'', true), ''''))',
      table_name
    );
  END LOOP;
END;
$$;

COMMENT ON SCHEMA admira IS 'Admira control-plane schema; tenant-scoped tables require LOCAL admira.tenant_id for RLS access.';
COMMENT ON COLUMN admira.tenants.id IS 'Tenant/workspace identity. Never use Telegram chat ID as the tenant key.';
COMMENT ON TABLE admira.tenants IS 'Tenant registry. RLS is intentionally fail-closed; provisioning must use a narrowly scoped trusted control-plane path before setting tenant context.';
COMMENT ON TABLE admira.tenant_telegram_updates IS 'Durable Telegram inbox/idempotency ledger. One shared bot is supported; (bot_id, update_id) is globally unique.';
COMMENT ON COLUMN admira.tenant_runtime_leases.lease_token IS 'Fencing token for a single active runtime owner.';
COMMENT ON TABLE admira.tenant_audit_events IS 'Append-only audit stream; application role should receive INSERT/SELECT, not UPDATE/DELETE.';

COMMIT;
