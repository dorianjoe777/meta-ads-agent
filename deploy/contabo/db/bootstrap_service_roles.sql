-- Environment-specific login roles. Passwords are read by PostgreSQL from
-- Docker secrets and never appear in repository files, argv, or psql output.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admira_image') THEN
    CREATE ROLE admira_image NOLOGIN;
  END IF;
END;
$$;

DO $$
DECLARE
  item record;
  password_value text;
BEGIN
  FOR item IN SELECT * FROM (VALUES
    ('admira_ingress_login',  'admira_ingress',  '/run/admira-db-secrets/ingress_db_password'),
    ('admira_runtime_login',  'admira_runtime',  '/run/admira-db-secrets/runtime_db_password'),
    ('admira_delivery_login', 'admira_delivery', '/run/admira-db-secrets/delivery_db_password'),
    ('admira_scheduler_login','admira_scheduler','/run/admira-db-secrets/scheduler_db_password'),
    ('admira_provisioner_login','admira_provisioner','/run/admira-db-secrets/provisioner_db_password'),
    ('admira_image_login',    'admira_image',    '/run/admira-db-secrets/image_db_password'),
    ('admira_recovery_login','admira_recovery','/run/admira-db-secrets/recovery_db_password'),
    ('admira_email_delivery_login','admira_email_delivery','/run/admira-db-secrets/email_delivery_db_password'),
    ('admira_operator_login','admira_operator','/run/admira-db-secrets/operator_db_password')
  ) AS roles(login_role, group_role, secret_path)
  LOOP
    -- bootstrap-control-plane.sh terminates each secret with one newline.
    -- Remove only line endings so the server password exactly matches the
    -- value returned by the workers' secret-file readers.
    password_value := regexp_replace(pg_read_file(item.secret_path), E'[\\r\\n]+$', '', 'g');
    IF length(password_value) < 32 THEN
      RAISE EXCEPTION 'service database password is missing or too short';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = item.login_role) THEN
      EXECUTE format('CREATE ROLE %I LOGIN INHERIT CONNECTION LIMIT 8', item.login_role);
    END IF;
    EXECUTE format('ALTER ROLE %I LOGIN INHERIT CONNECTION LIMIT 8 PASSWORD %L', item.login_role, password_value);
    EXECUTE format('GRANT %I TO %I', item.group_role, item.login_role);
    EXECUTE format('ALTER ROLE %I SET statement_timeout = %L', item.login_role, '30s');
    EXECUTE format('ALTER ROLE %I SET idle_in_transaction_session_timeout = %L', item.login_role, '15s');
  END LOOP;
END;
$$;

-- A short-lived pre-release dashboard build inherited the broad provisioner
-- group. Re-running the bootstrap must remove that membership, not merely add
-- the dedicated role beside it.
REVOKE admira_provisioner FROM admira_operator_login;
ALTER ROLE admira_operator_login
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
