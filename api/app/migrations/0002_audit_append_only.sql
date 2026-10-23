-- Runtime users may append/read tenant-scoped audit records, never rewrite history.
-- Privileged migration/backup operators retain administrative recovery rights.
REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.audit_events FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hello_app') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.audit_events FROM hello_app;
        GRANT SELECT, INSERT ON TABLE public.audit_events TO hello_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hello_worker') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE public.audit_events FROM hello_worker;
    END IF;
END $$;
