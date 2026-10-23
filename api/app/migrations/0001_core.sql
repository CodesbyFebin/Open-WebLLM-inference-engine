CREATE TABLE IF NOT EXISTS tenants (
    tenant_id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    disabled BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS users_email_ci ON users (lower(email));
CREATE INDEX IF NOT EXISTS users_tenant ON users (tenant_id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash CHAR(64) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id, expires_at);

CREATE TABLE IF NOT EXISTS auth_login_attempts (
    attempt_key CHAR(64) PRIMARY KEY,
    window_started TIMESTAMPTZ NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tenant_quotas (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    daily_requests INTEGER NOT NULL DEFAULT 100 CHECK (daily_requests BETWEEN 1 AND 1000000),
    daily_tokens BIGINT NOT NULL DEFAULT 100000 CHECK (daily_tokens BETWEEN 1 AND 1000000000)
);

CREATE TABLE IF NOT EXISTS usage_daily (
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    usage_date DATE NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    reserved_tokens BIGINT NOT NULL DEFAULT 0 CHECK (reserved_tokens >= 0),
    actual_tokens BIGINT NOT NULL DEFAULT 0 CHECK (actual_tokens >= 0),
    PRIMARY KEY (tenant_id, usage_date)
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    actor_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_events_tenant_time ON audit_events (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
    job_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    payload JSONB NOT NULL,
    result JSONB,
    usage_date DATE NOT NULL DEFAULT current_date,
    reserved_tokens INTEGER NOT NULL DEFAULT 0 CHECK (reserved_tokens >= 0),
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_claim ON jobs (status, available_at, lease_expires_at);
CREATE INDEX IF NOT EXISTS jobs_tenant_time ON jobs (tenant_id, created_at DESC);

ALTER TABLE tenant_quotas ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_quotas FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_quotas_isolation ON tenant_quotas;
CREATE POLICY tenant_quotas_isolation ON tenant_quotas USING
    (tenant_id::text = current_setting('hello.tenant_id', true)) WITH CHECK
    (tenant_id::text = current_setting('hello.tenant_id', true));

ALTER TABLE usage_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_daily FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS usage_daily_isolation ON usage_daily;
CREATE POLICY usage_daily_isolation ON usage_daily USING
    (tenant_id::text = current_setting('hello.tenant_id', true)) WITH CHECK
    (tenant_id::text = current_setting('hello.tenant_id', true));

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_events_isolation ON audit_events;
CREATE POLICY audit_events_isolation ON audit_events USING
    (tenant_id::text = current_setting('hello.tenant_id', true)) WITH CHECK
    (tenant_id::text = current_setting('hello.tenant_id', true));

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS jobs_isolation ON jobs;
CREATE POLICY jobs_isolation ON jobs USING
    (tenant_id::text = current_setting('hello.tenant_id', true)) WITH CHECK
    (tenant_id::text = current_setting('hello.tenant_id', true));

CREATE OR REPLACE FUNCTION hello_claim_job(p_worker TEXT, p_lease_seconds INTEGER DEFAULT 60)
RETURNS SETOF jobs
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE expired jobs%ROWTYPE;
BEGIN
    FOR expired IN
        UPDATE jobs SET status='failed', lease_owner=NULL, lease_expires_at=NULL,
            reserved_tokens=0, updated_at=now()
        WHERE status='running' AND lease_expires_at <= now()
          AND (attempt >= max_attempts OR submitted_at IS NOT NULL)
        RETURNING *
    LOOP
        PERFORM set_config('hello.tenant_id', expired.tenant_id::text, true);
        UPDATE usage_daily SET reserved_tokens=greatest(0,reserved_tokens-expired.reserved_tokens)
        WHERE tenant_id=expired.tenant_id AND usage_date=expired.usage_date;
        INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata)
        VALUES (expired.tenant_id,NULL,'job.failed',expired.job_id::text,
                jsonb_build_object('attempt',expired.attempt,'reason','lease expired'));
    END LOOP;
    RETURN QUERY
    WITH candidate AS (
        SELECT job_id FROM jobs
        WHERE attempt < max_attempts AND available_at <= now()
          AND (status='queued' OR (status='running' AND lease_expires_at <= now() AND submitted_at IS NULL))
        ORDER BY available_at, created_at
        FOR UPDATE SKIP LOCKED LIMIT 1
    )
    UPDATE jobs j SET status='running', attempt=j.attempt+1,
        lease_owner=p_worker,
        lease_expires_at=now()+make_interval(secs=>greatest(1,least(p_lease_seconds,600))),
        updated_at=now()
    FROM candidate c WHERE j.job_id=c.job_id RETURNING j.*;
END;
$$;

CREATE OR REPLACE FUNCTION hello_finish_job(p_job UUID, p_worker TEXT, p_result JSONB, p_error TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE j jobs%ROWTYPE;
DECLARE actual INTEGER := 0;
DECLARE failure TEXT := p_error;
BEGIN
    SELECT * INTO j FROM jobs WHERE job_id=p_job FOR UPDATE;
    IF NOT FOUND OR j.status <> 'running' OR j.lease_owner <> p_worker THEN
        RETURN FALSE;
    END IF;
    PERFORM set_config('hello.tenant_id', j.tenant_id::text, true);
    IF failure IS NULL THEN
        actual := greatest(0, coalesce((p_result->>'completion_tokens')::integer,0));
        IF jsonb_typeof(p_result) <> 'object' OR actual <= 0 OR actual > j.reserved_tokens
           OR coalesce(p_result->>'content','') = '' THEN
            failure := 'invalid worker result or token budget exceeded';
            actual := 0;
        END IF;
    END IF;
    IF failure IS NOT NULL AND j.submitted_at IS NULL AND j.attempt < j.max_attempts
       AND failure NOT LIKE 'terminal:%' THEN
        UPDATE jobs SET status='queued', available_at=now()+make_interval(secs=>least(30,2^attempt)),
            lease_owner=NULL, lease_expires_at=NULL, updated_at=now()
        WHERE job_id=p_job;
        RETURN TRUE;
    END IF;
    IF failure IS NULL THEN
        UPDATE jobs SET status='succeeded', result=p_result, lease_owner=NULL,
            lease_expires_at=NULL, reserved_tokens=0, updated_at=now() WHERE job_id=p_job;
    ELSE
        UPDATE jobs SET status='failed', result=jsonb_build_object('error','worker request failed'),
            lease_owner=NULL, lease_expires_at=NULL, reserved_tokens=0, updated_at=now()
        WHERE job_id=p_job;
    END IF;
    UPDATE usage_daily SET reserved_tokens=greatest(0,reserved_tokens-j.reserved_tokens),
        actual_tokens=actual_tokens+actual WHERE tenant_id=j.tenant_id AND usage_date=j.usage_date;
    INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata)
    VALUES (j.tenant_id,NULL,CASE WHEN failure IS NULL THEN 'job.succeeded' ELSE 'job.failed' END,
            j.job_id::text,jsonb_build_object('attempt',j.attempt,'completion_tokens',actual));
    RETURN TRUE;
END;
$$;
CREATE OR REPLACE FUNCTION hello_mark_job_started(p_job UUID, p_worker TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    UPDATE jobs SET submitted_at=now(), updated_at=now()
    WHERE job_id=p_job AND status='running' AND lease_owner=p_worker AND submitted_at IS NULL;
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION hello_create_user(p_tenant UUID, p_email TEXT, p_password_hash TEXT, p_role TEXT)
RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE created UUID;
BEGIN
    IF p_tenant::text <> coalesce(current_setting('hello.tenant_id', true),'') THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE='42501';
    END IF;
    IF p_role NOT IN ('admin','member','viewer') OR length(p_password_hash) > 200
       OR length(trim(p_email)) < 3 OR length(trim(p_email)) > 320 THEN
        RAISE EXCEPTION 'invalid account parameters' USING ERRCODE='22023';
    END IF;
    INSERT INTO users(user_id,tenant_id,email,password_hash,role)
    VALUES (gen_random_uuid(),p_tenant,lower(trim(p_email)),p_password_hash,p_role)
    RETURNING user_id INTO created;
    RETURN created;
END;
$$;
REVOKE ALL ON FUNCTION hello_claim_job(TEXT,INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION hello_mark_job_started(UUID,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION hello_finish_job(UUID,TEXT,JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION hello_create_user(UUID,TEXT,TEXT,TEXT) FROM PUBLIC;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hello_app') THEN
        GRANT USAGE ON SCHEMA public TO hello_app;
        GRANT SELECT ON tenants, users, schema_migrations TO hello_app;
        GRANT SELECT, INSERT, UPDATE ON sessions TO hello_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON auth_login_attempts TO hello_app;
        GRANT SELECT ON tenant_quotas TO hello_app;
        GRANT EXECUTE ON FUNCTION hello_create_user(UUID,TEXT,TEXT,TEXT) TO hello_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON usage_daily, audit_events, jobs TO hello_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hello_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hello_worker') THEN
        GRANT USAGE ON SCHEMA public TO hello_worker;
        GRANT EXECUTE ON FUNCTION hello_claim_job(TEXT,INTEGER) TO hello_worker;
        GRANT EXECUTE ON FUNCTION hello_mark_job_started(UUID,TEXT) TO hello_worker;
        GRANT EXECUTE ON FUNCTION hello_finish_job(UUID,TEXT,JSONB,TEXT) TO hello_worker;
    END IF;
END $$;
