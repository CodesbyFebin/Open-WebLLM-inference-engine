-- Execute as staging database administrator.
INSERT INTO control.tenants(id,name) VALUES
('aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa','tenant-a'),
('bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb','tenant-b');
INSERT INTO control.principals(tenant_id,subject,role) VALUES
('aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa','alice','owner'),
('bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb','bob','owner');
SET ROLE openwebllm_app;
BEGIN;
SELECT set_config('app.tenant_id','aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa',true);
DO $$
BEGIN
  IF (SELECT count(*) FROM control.tenants) <> 1 THEN
    RAISE EXCEPTION 'RLS tenant-a visibility violated';
  END IF;
  IF (SELECT count(*) FROM control.principals) <> 1 THEN
    RAISE EXCEPTION 'RLS principal isolation violated';
  END IF;
  IF (SELECT count(*) FROM control.principals WHERE subject='bob') <> 0 THEN
    RAISE EXCEPTION 'RLS exposed a cross-tenant principal';
  END IF;
END $$;
ROLLBACK;
BEGIN;
SELECT set_config('app.tenant_id','bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb',true);
DO $$
BEGIN
 IF (SELECT count(*) FROM control.tenants) <> 1 THEN
   RAISE EXCEPTION 'RLS tenant-b visibility violated';
 END IF;
 IF (SELECT count(*) FROM control.principals WHERE subject='alice') <> 0 THEN
   RAISE EXCEPTION 'RLS exposed tenant-a principal';
 END IF;
END $$;
ROLLBACK;
-- An app transaction without a tenant context must fail closed.
DO $$
BEGIN
 IF (SELECT count(*) FROM control.principals) <> 0 THEN
   RAISE EXCEPTION 'RLS leaked rows without tenant context';
 END IF;
END $$;
RESET ROLE;
