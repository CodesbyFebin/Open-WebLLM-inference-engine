# Self-host deployment (free-only, operator-controlled)

This deploy path builds the React console, the Python API, PostgreSQL and an HTTPS reverse proxy.
It does **not** provision cloud compute, a GPU, model service, DNS, domain, or paid API usage.
Use an existing Linux host you own and a domain you already control. Certificates are
obtained by the proxy only after the host is started with reachable ports 80/443.

## Prerequisites

- Linux host with Docker Compose v2, outbound access for image/package downloads and
  enough disk for PostgreSQL/builds; review network and data-transfer costs yourself.
- Existing domain resolving to your public host; ports TCP 80/443 (and optionally UDP 443).
- Operator-controlled, access-restricted OpenAI-compatible completion server, **optional**
  for browser WebGPU only; if absent, server inference returns unavailable.
- A private backup destination and a tested way to restore the database.

## Prepare configuration

1. Copy `.env.example` to `.env` and generate **five different** secrets using
   `openssl rand -hex 32`. Never commit `.env`. Set `SITE_DOMAIN`.
2. Keep `NIM_ENABLED=false`. Do not set a paid remote inference URL.
3. To enable server inference, set `INFERENCE_URL` to a trusted local/private endpoint
   and `INFERENCE_MODEL` to its exact served model. For a service on the Docker host,
   explicitly configure reachable networking rather than assuming localhost is shared.
4. Run `docker compose -f compose.deploy.yml config --quiet` to validate interpolation.
5. Run `docker compose -f compose.deploy.yml up -d --build postgres migrate gateway https`.
   This builds/starts local containers only; no model is downloaded by this stack.
6. Check HTTPS in a browser and `curl -fsS https://YOUR_DOMAIN/health`.
7. Create the first account using the existing migration/bootstrap CLI on an isolated
   console. Never expose bootstrap commands as unauthenticated public endpoints.

The optional worker profile is **disabled** unless separately activated. Only activate
it with an approved reachable local model server:
`docker compose -f compose.deploy.yml --profile workers up -d worker`.

## Operations

- **Backups:** schedule encrypted PostgreSQL backups to storage you control; verify
  a separate restore routinely. A one-time CI fixture restore does not establish PITR.
- **Monitoring:** collect container health, database metrics, gateway Prometheus metrics
  with authenticated collectors, certificate expiry and error rates. Add an actual
  alert destination before public launch.
- **Rollback:** preserve the previous image digests and a compatible DB schema.
  Test rollback in a staging copy; migrations may not be reversible.
- **Secrets:** use a private env file restricted to the deployment operator and
  rotate compromised credentials. Do not expose DB or gateway ports directly.
- **Security:** keep this behind VPN/IP access control until independent assessment,
  signed-off TLS, abuse protection and retention review. HTTPS alone is not a security audit.

## Evidence boundary

This is a **deployment configuration**, not a verified external deployment. Browser
WebGPU still requires a capable physical device and model-download consent.
Real GPU throughput, app-level failover, failover cost and OpenShell sandbox tests
remain unqualified. Never describe them as passed based on `docker compose config`.
