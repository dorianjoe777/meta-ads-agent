-- Environment-specific login roles. Passwords are read by PostgreSQL from
-- Docker secrets and never appear in repository files, argv, or psql output.
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
    ('admira_provisioner_login','admira_provisioner','/run/admira-db-secrets/provisioner_db_password')
  ) AS roles(login_role, group_role, secret_path)
  LOOP
    password_value := btrim(pg_read_file(item.secret_path));
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
