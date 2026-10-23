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

## Upstream sourcing and licensing

Use adapters against upstream runtimes, not a bulk copy of unrelated source trees. Checked repository metadata on 2026-10-23:

| Upstream | Repository license | Decision |
| --- | --- | --- |
| vllm-project/vllm | Apache-2.0 | External GPU service |
| mlc-ai/web-llm | Apache-2.0 | Separate browser runtime planned |
| Comfy-Org/ComfyUI | GPL-3.0 | External workflow service; do not blend source into this gateway |
| alibaba/MNN | Apache-2.0 | Native mobile adapter planned |
| cactus-compute/cactus | Not asserted in API metadata | Review license before reuse |
| OpenNMT/CTranslate2 | MIT | Separate native adapter planned |
| google/gemma.cpp | Apache-2.0 | Model-specific local engine reference |
| NVIDIA/TransformerEngine | Apache-2.0 | CUDA library, not an inference API |
| Michael-A-Kuykendall/shimmy | Apache-2.0 | OpenAI-compatible local service candidate |

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

## Studied, not integrated (2026-10-23)

`docs/upstream-skills/` records techniques from 50 shallow clones (WebGPU device loss, WASM feature detection, VerifyFetch-style resumable hashed downloads, Comlink worker RPC, separate Transformers.js vs WebLLM artifacts, and page-local WebMCP tools). Licensed notes are copied. Unlicensed repositories are links only. None of these techniques are adapters. Do not mark WebLLM, ComfyUI, or a browser worker pool as implemented because the notes exist.
