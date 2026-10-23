# Backend adapters — selection and integration contract

All engines are external dependencies, not vendored code. The gateway registry describes what is implemented and what remains a separate integration. Do not interpret `configured` as a passing health check.

| Engine | Format | Target hardware | Implementation |
|---|---|---|---|
| Transformers.js | ONNX q4f16 | Browser WebGPU | Worker included; requires per-device test |
| vLLM | Hugging Face safetensors | NVIDIA GPU | OpenAI-compatible proxy + Docker/K8s |
| WebLLM | MLC model artifacts | Browser WebGPU | Not implemented |
| ComfyUI | Graph/JSON workflow with model-specific weights | GPU workflow host | Not implemented |
| MNN | MNN/native models | ARM/mobile | Not implemented |
| Cactus | Runtime-specific mobile weights | Mobile/edge | Not implemented |
| CTranslate2 | CTranslate2 converted models | CPU/GPU | Not implemented |

## Integration rules

1. Keep task-specific APIs distinct. Do not route diffusion workflow payloads to a text completions endpoint.
2. Implement each provider adapter with explicit health, model list, request schema, cancellation and measured metrics.
3. Browser routing is a decision returned to the client; the server cannot execute the user's browser worker.
4. Sensitivity policy fails closed if local execution is unavailable. Regex redaction alone is not an enterprise-grade PII privacy layer.
5. Never claim prefetched KV blocks or physical block maps unless the runtime exposes verifiable instrumentation.
6. Quantization choices are separate model artifacts; switching precision requires artifact availability and loading costs.
7. Compare speed with repeated warm/cold benchmarks on specified hardware, never upstream marketing claims.

## Next validated integrations

- WebLLM adapter with preflight WebGPU capability detection and MLC model manifest.
- ComfyUI asynchronous queue adapter with workflow allowlist and job polling.
- Local runtime discovery for OpenAI-compatible endpoints with sandboxed network policy.
- Mobile bridge with native Android smoke tests for MNN/Cactus.
- Prometheus GPU metrics, queue depth, p50/p95 TTFT and abort propagation.
