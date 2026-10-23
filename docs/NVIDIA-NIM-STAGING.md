# Hosted NVIDIA NIM staging qualification

Target: `nvidia/nemotron-3.5-lightning-30b-a3b` on NVIDIA's documented free development endpoint.

## Safety and authorization

- No paid GPU machines, cloud resources, or NIM containers are provisioned.
- This GitHub Action runs **only by manual workflow dispatch**; pushes and pull requests cannot trigger inference.
- Confirm NVIDIA still offers the model to **your own account** under free development quota before each run. The form requires the exact phrase `I CONFIRM FREE ONLY`. This is a human confirmation, **not a programmatic billing guarantee**.
- Three requests maximum: one each for simple, reasoning, and code, with `max_tokens=48`; on any failure the script stops.
- The workflow has a 5-minute timeout and the individual request has a 45-second timeout. It does not retry. Generated content, credentials, response headers, and provider error bodies are not written to logs or uploaded.
- Measurements are GitHub Action artifacts retained seven days and **do not enable automatic routing**.

## Setup

1. Configure repository Actions secret `NVIDIA_API_KEY` in GitHub Settings. Do not paste it into an issue, pull request, file, or chat.
2. Verify availability on [NVIDIA's model page](https://build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b/build). An advertised free endpoint does not prove that every account has free quota.
3. Merge the reviewed workflow and runner. Under **Actions → NVIDIA NIM free-quota qualification → Run workflow**, enter `I CONFIRM FREE ONLY` only if you have verified free entitlement.
4. Download `nvidia-nim-qualification` from the completed workflow run, inspect `qualified`, timestamps, and latency measurements.

## Acceptance and limitations

A pass requires completed streamed generated text, provider-reported completion-token usage, and measured TTFT/throughput across all three categories on the **same exact model**. Missing usage causes a failure rather than an estimate. Three smoke requests are not performance confidence intervals, model accuracy tests, or long-duration load evidence.

This qualifies the **NVIDIA-hosted NIM API path**, not a specific physical GPU, CUDA driver, KV-cache implementation, distributed scheduler, mobile GPU, or self-hosted NIM deployment. It must not be treated as production-readiness evidence. Use a private staging environment and separate hardware benchmarks before enabling automatic routing.

The current repository's FastAPI gateway has its own benchmarking and evidence store; this GitHub Action intentionally does **not** modify or insert records into that runtime database. A reviewed import/attestation step would be needed for a promotion gate.
