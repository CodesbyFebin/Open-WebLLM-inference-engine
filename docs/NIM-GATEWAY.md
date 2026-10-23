# NVIDIA NIM application adapter (staging only)

The hosted NVIDIA NIM smoke qualification passed in GitHub Actions run #3, but this does not certify dedicated GPU provisioning or production capacity.

The gateway exposes two **authenticated** routes:
- `GET /api/nim/status`: configuration and in-process remaining request slots (never returns the key).
- `POST /api/nim/complete`: single non-streaming chat request using the pinned `nvidia/nemotron-3.5-lightning-30b-a3b` model.

The adapter defaults to **disabled**. The GitHub Actions `NVIDIA_API_KEY` secret is available only inside GitHub Actions and is **not** automatically injected into deployed servers. To opt in for a trusted private staging process, configure:

```dotenv
API_KEY=your-private-gateway-auth-token
NVIDIA_API_KEY=your-provider-secret
NIM_ENABLED=true
NIM_FREE_QUOTA_ACK=I CONFIRM FREE ONLY
NIM_MAX_REQUESTS=1
```

The `NIM_MAX_REQUESTS` setting is clamped to a maximum of three per process. Output is limited to 48 tokens; input is limited to 2,000 characters; the upstream endpoint and model are pinned; there are no automatic retries or fallback calls. An attempted request consumes its in-process slot even if upstream fails.

**Billing warning:** these in-process controls are not an account-level spend ceiling and reset when a process restarts or replicas scale. The operator must independently verify remaining free entitlement in NVIDIA's account console. Do not expose or enable this adapter on publicly shared deployments. No paid resources are authorized.

## Promotion gates still open

- Tenant-scoped sessions, authorization and durable cross-replica quotas.
- Durable PostgreSQL audit and request accounting.
- Provider rate-limit and failover testing under explicit quota.
- Browser WebGPU/LiteRT physical-device verification.
- Sustained load, TLS, monitoring, backup/restore, and adversarial security assessment.

For free-only usage, leave `NIM_ENABLED=false` unless entitlement has been checked immediately before a bounded staging run.
