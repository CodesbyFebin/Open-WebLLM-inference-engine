# Production gates — evidence register

Status is based on executed evidence, not configuration files.

| Gate | Status | Evidence / blocker |
| --- | --- | --- |
| NVIDIA hosted NIM 3-request smoke | PASS (bounded) | GitHub Actions run 40005090155; not dedicated GPU qualification |
| Authenticated NVIDIA NIM adapter | CI PASS | PR #2; intentionally disabled by default |
| PostgreSQL migration/RLS/quota concurrency/restore | CI qualification pending | Disposable GitHub Actions PostgreSQL 16, this PR |
| Multi-user verified sessions and RBAC | NOT RUN / NOT IMPLEMENTED | No hosted identity provider or verified principal-to-tenant binding |
| Tenant isolation at all APIs/workers | NOT IMPLEMENTED | Database RLS schema alone cannot enforce application identity |
| External persistent Postgres backup/PITR | NOT RUN | Requires authorized disposable staging database and restore target |
| Long-running Docker workers/crash recovery | NOT RUN | No production worker runtime provisioned |
| OpenShell hostile execution | NOT RUN | Approved isolated OpenShell host unavailable |
| Load and failover benchmarks | NOT RUN | Requires bounded environment with known account-level spend guarantee |
| Physical WebGPU and LiteRT-LM | NOT RUN | Requires physical test devices and device logs |
| Production TLS/monitoring/rollback | NOT RUN | Requires production-like ingress, DNS, monitoring receiver and staging deployment |
| Independent security review | NOT RUN | Requires a deployed target and reviewer independent of implementer |

## PostgreSQL schema boundaries

`api/migrations/001_control_plane.sql` creates relational tenants, principals,
hashed session-token storage, quotas, jobs and tenant-scoped audit events.
FORCE ROW LEVEL SECURITY is enabled on all tables for the `openwebllm_app`
role. A trusted server **must** validate a session token and then issue
`SET LOCAL app.tenant_id` inside each transaction; accepting arbitrary tenant IDs
from client input would defeat isolation. The database role is intentionally
`NOLOGIN` as provided; production provisioning must create a separate restricted
login role with an audited role-switching strategy.

The disposable CI flow validates table migration, a two-tenant RLS fixture,
20 simultaneous quota allocations with a limit of five, and restoring a
`pg_dump` archive into a second database. **This is not production backup
verification, PITR, or multi-node tenant qualification.**

## External staging prerequisite checklist

1. Disposable PostgreSQL and separately credentialed migration/app/worker roles.
2. Approved isolated Docker Linux runner and OpenShell environment.
3. At least two non-production authenticated principals in separate tenants.
4. Strictly capped local and remote inference endpoints with account-level free allowance confirmed.
5. Physical WebGPU/LiteRT-LM devices for captured logs.
6. Owned test domain, TLS ingress, metrics receiver, alert destination, rollback candidate.
7. Independent security assessor with approved staging scope.

No paid infrastructure may be allocated under the current free-only authorization.
