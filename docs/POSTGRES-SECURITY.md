# PostgreSQL identity and tenant security

The gateway supports database-backed user sessions when `DATABASE_URL` is set. `MIGRATION_DATABASE_URL` is a separate, privileged connection used only by `python -m app.migrate` in a restricted release job; it is not needed by the running gateway. Production mode fails startup when `DATABASE_URL` or a 32+ character `AUTH_THROTTLE_PEPPER` is absent. Login failures are keyed by a peppered email/IP digest and trigger a 15-minute lock after five failures. The old shared `API_KEY` is retained for local and machine use only; with a database configured it is disabled unless `ALLOW_MACHINE_API_KEY=true` is explicitly set.

## Capabilities

- Email/password login issues a random bearer session. Only a SHA-256 digest is persisted. Sessions expire after 12 hours and can be revoked. Tenant owners can provision roles through the authenticated admin API; open registration is not enabled.
- Roles are `owner`, `admin`, `member`, and `viewer`. Inference requires owner/admin/member; benchmark runs require owner/admin.
- Tenant IDs are derived from the authenticated session. They are not accepted from request bodies. PostgreSQL row-level security is forced for quota, usage, and audit tables and enabled for jobs; only security-definer lease functions can operate across tenants for the isolated worker role.
- Inference reserves the requested output-token budget atomically against per-tenant daily request and token caps. A successful provider response settles using provider-reported usage; failures release the token reservation. Requests and security-relevant actions are recorded without prompts or credentials.
- A bootstrap command creates the initial tenant owner through the privileged connection: `cd api && MIGRATION_DATABASE_URL=... python -m app.bootstrap` (after applying migrations).
- Inference jobs are durable rows claimed with `FOR UPDATE SKIP LOCKED` and time-limited leases. A crash before the provider-call boundary can be reclaimed. After that boundary is persisted, an expired job fails without replay so a non-idempotent request is not blindly sent again. This is at-most-once after submission, not exactly-once; a crash after provider completion but before result persistence can leave provider usage uncertain.

## Connection roles

The database app role needs only `CONNECT`, schema `USAGE`, selected reads from tenants/users/session metadata, session insert/update, and tenant-scoped table DML with RLS. It must not own tables or have `BYPASSRLS`. The worker role can call only narrow job lease/settlement functions and has no direct table privileges. The migration role owns schema changes and should not be mounted into the gateway in production. Use distinct credentials and rotate all three roles plus `AUTH_THROTTLE_PEPPER`. Do not set `ALLOW_MACHINE_API_KEY` in a shared production service.

## Qualification

**PASS — GitHub Actions run [#46](https://github.com/CodesbyFebin/Open-WebLLM-inference-engine/actions/runs/40018048338)** completed the container-policy build, API suite, PostgreSQL security integration suite, and browser tests/build. **PASS — PostgreSQL isolation and recovery run [#15](https://github.com/CodesbyFebin/Open-WebLLM-inference-engine/actions/runs/40018048144)** applied the isolated PostgreSQL 16 migration, verified two-tenant RLS, passed 20-way concurrent reservations against a quota of five, and restored a disposable `pg_dump` archive.

The database-backed suite creates separate migration, application, and worker roles and exercises session validation/revocation/expiry, role provisioning and login lockout, cross-tenant RLS, atomic concurrent quota reservation, durable job lease recovery, and audit records. This verifies the code's PostgreSQL behavior; it does not qualify an operator's production cluster, backup retention policy, encryption, failover, or access controls.

The API/worker containers run non-root with read-only root filesystems, dropped Linux capabilities, and `no-new-privileges`. The worker handles bounded inference payloads only and has no shell/tool execution path. This configuration is not an OpenShell sandbox and is not a substitute for one when arbitrary code or tools are introduced. This qualification does not prove an independent security assessment, live configured inference performance, physical GPU tests, or production TLS/monitoring/rollback drills.
