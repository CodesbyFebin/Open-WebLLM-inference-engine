-- Open Web LLM staging schema v1. Apply using an administrator, never the app role.
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'openwebllm_app') THEN
    CREATE ROLE openwebllm_app NOLOGIN NOBYPASSRLS;
  END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS control;
CREATE TABLE IF NOT EXISTS control.tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS control.principals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  subject text NOT NULL, role text NOT NULL CHECK (role IN ('owner','admin','member','viewer')),
  disabled_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id,subject), UNIQUE (id,tenant_id)
);
CREATE TABLE IF NOT EXISTS control.sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  principal_id uuid NOT NULL,
  token_sha256 bytea NOT NULL UNIQUE CHECK (octet_length(token_sha256)=32),
  expires_at timestamptz NOT NULL, revoked_at timestamptz,
  FOREIGN KEY (principal_id,tenant_id) REFERENCES control.principals(id,tenant_id)
);
CREATE TABLE IF NOT EXISTS control.quotas (
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  period_start date NOT NULL, request_limit integer NOT NULL CHECK (request_limit>=0),
  requests_used integer NOT NULL DEFAULT 0 CHECK (requests_used>=0),
  PRIMARY KEY(tenant_id,period_start),
  CHECK(requests_used<=request_limit)
);
CREATE TABLE IF NOT EXISTS control.jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','leased','done','failed','uncertain')),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  lease_owner text, leased_until timestamptz, attempts integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS control.audit_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES control.tenants(id),
  principal_id uuid, action text NOT NULL, resource_id text,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  FOREIGN KEY (principal_id,tenant_id) REFERENCES control.principals(id,tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON control.audit_events(tenant_id,occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_ready ON control.jobs(state,leased_until);
REVOKE ALL ON SCHEMA control FROM PUBLIC;
GRANT USAGE ON SCHEMA control TO openwebllm_app;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA control TO openwebllm_app;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA control TO openwebllm_app;
-- Tenant identity MUST be bound by a trusted application after validating a session.
-- Never expose arbitrary SQL or tenant-context setters to untrusted clients.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['tenants','principals','sessions','quotas','jobs','audit_events'] LOOP
    EXECUTE format('ALTER TABLE control.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE control.%I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_boundary ON control.%I',t);
    IF t = 'tenants' THEN
      EXECUTE format('CREATE POLICY tenant_boundary ON control.%I TO openwebllm_app USING (id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
    ELSE
      EXECUTE format('CREATE POLICY tenant_boundary ON control.%I TO openwebllm_app USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',t);
    END IF;
  END LOOP;
END $$;
COMMIT;
