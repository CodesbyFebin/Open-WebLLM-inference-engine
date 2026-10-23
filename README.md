# Open WebGPU Inference Engine

**CodesbyFebin · Open inference infrastructure for browser, edge, and GPU.**

This repository begins with a working-source foundation: React/TypeScript WebGPU inference console, FastAPI gateway, authenticated routing and vLLM deployment manifests. Runtime integrations have individually declared states, and unfinished adapters are not advertised as runnable.

## Studied techniques

`docs/upstream-skills/TECHNIQUES.md` merges notes from browser WebGPU, worker, and on-device model repositories. The notes are not vendored runtimes. WebLLM remains a planned separate adapter. Unlicensed upstream trees were not copied.

## Runtime support matrix

| Runtime | Use | State |
| --- | --- | --- |
| Transformers.js | ONNX q4f16 browser text generation | Implemented source; device validation pending |
| vLLM | GPU text generation | Configured; NVIDIA runtime validation pending |
| Local OpenAI-compatible server | Private edge node | Registry/routing capability; inference adapter pending |
| WebLLM | Browser MLC models | Planned separate adapter |
| ComfyUI | Image graph workflows | Planned workflow adapter |
| MNN / Cactus | Native mobile | Planned SDK bindings |

## Evidence-gated benchmarks

The gateway implements a real streaming benchmark protocol for configured OpenAI-compatible GPU and edge services. It records evidence in SQLite (`BENCHMARK_DB`) and refuses **automatic** server routing unless the latest three results cover distinct simple, reasoning, and code prompts, all contain model-generated text, and include provider-reported completion token counts. Results expire after 24 hours. This is a **performance/compatibility smoke gate**, not an accuracy certification.

```bash
curl -X POST http://127.0.0.1:8080/api/benchmarks/run \
  -H 'Authorization: Bearer YOUR_SECRET' -H 'Content-Type: application/json' \
  -d '{"backend":"gpu","repetitions":1}'
curl -H 'Authorization: Bearer YOUR_SECRET' http://127.0.0.1:8080/api/benchmarks/status
```

Running a benchmark submits real model requests and can incur GPU cost. It is never triggered automatically by web-page visits. The browser UI offers a separate measured browser benchmark; browser results cannot be attested by this gateway and are excluded from automatic server routing until a trusted device-verification flow exists.

`EDGE_URL`, `EDGE_MODEL`, and `EDGE_API_KEY` configure a private OpenAI-compatible edge service. All URLs are operator-configured environment variables, not supplied by untrusted inference callers.

All upstream projects remain independent, subject to their own licenses. The project does not vendor or claim ownership of their source code. Benchmarks such as latency, tokens/second, and GPU memory must come from actual runs.

## Architecture

```mermaid
flowchart TD
 UI[React console] --> Local[Transformers.js worker]
 UI --> Gateway[FastAPI gateway]
 Gateway --> Policy[Capability / privacy router]
 Policy --> GPU[vLLM GPU service]
 Policy --> Edge[Private edge adapter]
 Gateway --> Metrics[Prometheus telemetry]
```

The browser route is advisory: the frontend invokes the local worker itself. `/api/route` never fakes local execution or forwards confidential input to an unavailable runtime.

### Quick start

- Browser: `cd web && npm install && npm run dev`
- API: `cd api && pip install -r requirements.txt && uvicorn app.main:app --port 8080`
- GPU: set `API_KEY` in `.env`, then `docker compose up --build` on an NVIDIA-equipped host.
- Routing: `POST /api/route` with bearer authentication, prompt, privacy/quality policy, and `browser_available` flag.

The source is an initial integration baseline, **not a verified production deployment**. See the remaining setup and limitations below.

React/TypeScript browser inference console, FastAPI inference gateway, Docker Compose NVIDIA GPU stack, and GKE L4 infrastructure templates.

## Browser

Requires WebGPU-capable Chrome/Edge, RAM for model weights, and localhost or HTTPS.

```bash
cd web
npm install
npm run dev
```

The browser worker loads actual q4f16 ONNX weights via Transformers.js and streams model-generated text. Browser cache is managed by the Transformers.js runtime (not necessarily IndexedDB). It enforces the 384-token prompt limit **using the tokenizer**, after weight load. The block explorer is an explicitly labeled logical illustration based on whitespace-separated units, not a real GPU/ONNX page allocator. Streamer callbacks can be chunks rather than individual tokens; displayed chunk rate is not an exact tokens/s statistic.

## GPU with Docker

Requires NVIDIA Container Toolkit and enough VRAM for Qwen2.5-7B. Configure `.env`:

```dotenv
API_KEY=replace-with-random-long-secret
```

```bash
docker compose up --build
curl -H 'Authorization: Bearer replace-with-random-long-secret' http://127.0.0.1:8080/api/cache/status
```

The gateway listens only on localhost. Do not expose vLLM to the internet. Configure a local reverse proxy for the web UI when accessing the GPU endpoint (Vite dev server proxy or production same-origin reverse proxy). Cross-origin direct requests are intentionally not enabled by default.

## GPU on GKE

```bash
cd infra/terraform
terraform init
terraform plan -var='project_id=YOUR_GCP_PROJECT'
terraform apply -var='project_id=YOUR_GCP_PROJECT'
gcloud container clusters get-credentials inference-lab --region us-central1 --project YOUR_GCP_PROJECT
```

Build and push the gateway image to a private registry; replace the manifest image placeholder. Create a Kubernetes secret named `inference-credentials` with key `api-key`. Then deploy `infra/k8s/vllm.yaml` and `infra/k8s/gateway.yaml` and use `kubectl port-forward service/inference-gateway 8080:8080` for private access. GKE GPU VMs incur charges. Production clusters need restricted control plane ingress, policies, observability, quota and lifecycle management. Terraform is a starting template, not a complete hardened cluster configuration.

## API

- `POST /api/infer`: `{prompt, model, max_tokens, temperature, stream}` (configured GPU model; streaming proxies vLLM SSE).
- `GET /api/cache/status`: actual aggregate vLLM KV pool usage and hit rate where exported; `blockTable: null` means no physical block-level instrumentation.
- `GET /api/metrics`: gateway Prometheus text format.
- `GET /api/models`: configured GPU model.
- `GET /health`: gateway liveness only.

All `/api/*` routes require an `Authorization: Bearer ...` header matching `API_KEY`. The UI holds the token in ephemeral memory; do not give an untrusted multi-user frontend a shared production secret. Implement identity-aware session authentication before exposing this as a hosted service.

## Tests

```bash
cd api
pip install -r requirements.txt
pytest -q
cd ../web
npm install
npm test
npm run build
```

The browser unit test verifies exact 16-unit full-block matching. A live GPU prefix-cache integration test and GPU performance benchmark still require deployed NVIDIA hardware. Compare repeated 32+ model-token prompts against real vLLM exported hit/miss counters; aggregate metrics do not prove the ownership of any particular physical block.

## Known gaps

- Four ONNX model checkpoint metadata and compatibility need live browser validation on target devices.
- Backend-reported GPU total token counts are available, but GPU TTFT is not calculated from non-streaming requests.
- Kubernetes autoscaling, private tunnel management, GPU warm-up jobs and production-grade request limits remain to be implemented.
- vLLM metric names may vary by release; pin and verify against the running container.
- No GPU infrastructure has been provisioned or tested in this workspace.
