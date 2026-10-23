# Production gates — evidence register

Status is based on executed evidence, not configuration files.

| Gate | Status | Evidence / remaining limit |
| --- | --- | --- |
| NVIDIA NIM Nemotron 3.5 hosted smoke | PASS — bounded free-tier qualification | [Main run #4](https://github.com/CodesbyFebin/Open-WebLLM-inference-engine/actions/runs/40019320506) sent exactly three fixed prompts to `nvidia/nemotron-3.5-lightning-30b-a3b`, capped at 48 output tokens each. Simple, reasoning, and code prompts passed; non-sensitive measurements were uploaded. The workflow requires the explicit free-only acknowledgement. It does not independently inspect provider billing entitlement or verify GPU hardware. |
| Authenticated NIM gateway route | CI PASS | [PR #4](https://github.com/CodesbyFebin/Open-WebLLM-inference-engine/pull/4) and [CI run #48](https://github.com/CodesbyFebin/Open-WebLLM-inference-engine/actions/runs/40018208780); route uses a mocked upstream in tests. |
| Runtime PostgreSQL migration and role separation | CI PASS | [CI run #48](https://github.com/CodesbyFebin/Open-WebLLM-inference-engine/actions/runs/40018208780) applied migrations with a separate migration role and tested app/worker roles. |
| Session lifecycle, RBAC, and login throttling | CI PASS | Disposable PostgreSQL tests cover login, expiration, revocation, owner/admin/member/viewer authorization, provisioning, and lockout in CI run #48. This is application-owned email/password auth, not external identity-provider verification. |
| Tenant isolation, quota concurrency, and audit | CI PASS | Run #48 tests tenant RLS, isolation, atomic concurrent reservations, audit, worker privileges, jobs, and recovery. [PostgreSQL isolation run #17](https://github.com/CodesbyFebin/Open-WebLLM-inference-engine/actions/runs/40018209006) separately passes two-tenant RLS, 20 concurrent quota reservations capped at five, and disposable restore. Production-cluster isolation is not certified. |
| Disposable database backup and restore | PASS — CI fixture only | Runs #48 and #17 restore disposable `pg_dump` archives. Production retention, encryption, PITR, and operator recovery remain unverified. |
| Durable worker jobs and crash recovery | CI PASS | Run #48 tests leases, crash recovery, cancellation, and restricted worker table access. No continuously running production worker deployment or failover has been exercised. |
| Container policy | CI PASS | Run #48 validates Compose configuration, builds the API/worker image, and asserts the container runs as UID 65532. This is not an OpenShell sandbox. |
| Gateway concurrency | CI PASS — mocked upstream | The API suite sends concurrent requests through the gateway with a fake inference transport; provider throughput and failover are not measured. |
| OpenShell hostile-execution isolation | NOT RUN / NOT APPLICABLE TO CURRENT WORKER | The inference worker accepts bounded text prompts and has no shell, arbitrary code, or tool-execution path. An approved isolated OpenShell host is required before adding those capabilities. |
| Physical WebGPU / LiteRT-LM device validation | NOT RUN | Requires physical target devices and captured device logs. The hosted NIM run does not validate browser GPU hardware. |
| Production TLS, monitoring, alerting, rollback, and failover drills | NOT RUN | Requires an owned staging domain, deployed ingress, monitoring receiver, alert destination, production-like environment, and rollback candidate. |
| Independent security assessment | NOT RUN | Requires an independent assessor and an approved deployed target. |

## PostgreSQL identity and schema boundaries

The runtime schema is in `api/app/migrations/0001_core.sql`; the privileged migration command is `python -m app.migrate`. The gateway derives tenant identity from a validated session and scopes database operations to that tenant. Runtime quota, usage, and audit records use row-level security; worker job access is limited to lease and settlement functions.

The separate `api/migrations/001_control_plane.sql` schema is the earlier disposable RLS qualification fixture. It is not the runtime migration path. The fixture verifies RLS with a non-login app role; the runtime integration workflow creates its own migration, app, and worker credentials.

CI verifies migration and role setup, session handling, tenant separation, concurrent quota reservation, durable worker behavior, audit access, container policy, and a disposable backup restore. These checks do not certify production cluster configuration, encryption, retention, point-in-time recovery, multi-node behavior, or independent security review.

## Remaining external prerequisites

1. Staging infrastructure with separately managed migration, app, and worker credentials.
2. Production-like TLS ingress, monitoring, alert routing, rollback candidate, and failover plan.
3. Physical WebGPU/LiteRT-LM devices for target-device qualification.
4. An approved OpenShell host before any arbitrary-code or tool execution is added.
5. Independent security assessor and a deployed target.

No paid infrastructure or provider usage is authorized by this evidence register. The NIM qualification workflow must only be dispatched after confirming the model is covered by the user's NVIDIA free quota; it uses exactly three fixed prompts and 48 maximum output tokens per prompt.
