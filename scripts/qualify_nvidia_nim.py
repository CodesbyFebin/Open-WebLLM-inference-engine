#!/usr/bin/env python3
"""Bounded, manual-only hosted NVIDIA NIM smoke benchmark. No routing promotion."""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
PROMPTS = {
    "simple": "Reply with exactly one short greeting.",
    "reasoning": "In one sentence, explain why caching nondeterministic program output is risky.",
    "code": "Write a short Python factorial function with a nonnegative input check.",
}
OUTPUT = Path("nim-qualification.json")


def request_once(category, prompt, key):
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 48,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(
        ENDPOINT, data=payload, method="POST",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    started = time.monotonic()
    first_content = None
    emitted = 0
    tokens = None
    finished = False
    with urllib.request.urlopen(req, timeout=45) as resp:
        if resp.status != 200:
            raise RuntimeError("NVIDIA HTTP status " + str(resp.status))
        for raw in resp:
            if time.monotonic() - started > 45:
                raise RuntimeError("Response exceeded 45-second request budget")
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                finished = True
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if chunk.get("error"):
                raise RuntimeError("NIM streaming error")
            for choice in chunk.get("choices", []):
                delta = choice.get("delta") or {}
                content = delta.get("content") or ""
                if content:
                    if first_content is None:
                        first_content = time.monotonic()
                    emitted += len(content)
            usage = chunk.get("usage") or {}
            if isinstance(usage.get("completion_tokens"), int):
                tokens = usage["completion_tokens"]
    if not finished or first_content is None or emitted == 0 or not tokens:
        raise RuntimeError("Missing completed streaming output or provider-reported usage")
    elapsed = time.monotonic() - started
    return {
        "category": category,
        "status": "pass",
        "ttft_ms": round((first_content - started) * 1000, 2),
        "tokens_per_second": round(tokens / max(elapsed - (first_content - started), 0.001), 2),
        "completion_tokens": tokens,
    }


def main():
    # Never accept an arbitrary endpoint, model, prompt, or token budget from workflow inputs.
    if os.environ.get("NIM_FREE_QUOTA_ACK") != "I CONFIRM FREE ONLY":
        raise RuntimeError("Explicit free-quota confirmation is required")
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        raise RuntimeError("NVIDIA_API_KEY secret is unavailable")
    rows = []
    for category, prompt in PROMPTS.items():
        try:
            rows.append(request_once(category, prompt, key))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            # Deliberately avoid response bodies and request headers in public CI logs.
            rows.append({"category": category, "status": "fail", "error_type": type(exc).__name__})
            break
    result = {
        "schema_version": 1,
        "provider": "nvidia-nim-hosted",
        "model": MODEL,
        "endpoint_origin": "https://integrate.api.nvidia.com",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "actual_gpu_hardware_verified": False,
        "auto_routing_enabled": False,
        "measurements": rows,
        "qualified": len(rows) == 3 and all(r["status"] == "pass" for r in rows),
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"model": MODEL, "qualified": result["qualified"], "categories": [r["status"] for r in rows]}))
    if not result["qualified"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
