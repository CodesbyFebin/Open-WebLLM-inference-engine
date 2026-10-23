"""Explicitly gated NVIDIA hosted NIM adapter. No automatic paid fallback."""
import asyncio
import os
from typing import Any

import httpx
from fastapi import HTTPException

NIM_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
NIM_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
MAX_OUTPUT_TOKENS = 48
_lock = asyncio.Lock()
_request_count = 0

def readiness() -> dict[str, Any]:
    enabled = os.getenv("NIM_ENABLED") == "true"
    acknowledged = os.getenv("NIM_FREE_QUOTA_ACK") == "I CONFIRM FREE ONLY"
    has_key = bool(os.getenv("NVIDIA_API_KEY"))
    try:
        limit = int(os.getenv("NIM_MAX_REQUESTS", "0"))
    except ValueError:
        limit = 0
    limit = max(0, min(3, limit))
    return {"enabled": enabled and acknowledged and has_key and limit > 0,
            "model": NIM_MODEL, "remainingProcessRequests": max(0, limit - _request_count),
            "reason": None if enabled and acknowledged and has_key and limit > 0
                      else "NIM disabled or free-only authorization/credential/budget missing"}

async def complete(client: httpx.AsyncClient, prompt: str, max_tokens: int = 48) -> dict:
    global _request_count
    state = readiness()
    if not state["enabled"]:
        raise HTTPException(503, "NVIDIA NIM is not explicitly enabled for bounded free-only use")
    if max_tokens < 1 or max_tokens > MAX_OUTPUT_TOKENS:
        raise HTTPException(422, "NIM max_tokens must be 1..48")
    # Reserve before sending; errors consume a slot to avoid unbounded retries.
    async with _lock:
        remaining = readiness()["remainingProcessRequests"]
        if remaining <= 0:
            raise HTTPException(429, "NVIDIA NIM process request budget exhausted")
        _request_count += 1
    try:
        response = await client.post(
            NIM_ENDPOINT,
            headers={"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}"},
            json={"model": NIM_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": max_tokens, "temperature": 0, "stream": False,
                  "chat_template_kwargs": {"enable_thinking": False}},
            timeout=httpx.Timeout(45, connect=10),
        )
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        answer = (choices[0].get("message") or {}).get("content") if choices else None
        usage = (body.get("usage") or {}).get("completion_tokens")
        if not isinstance(answer, str) or not answer.strip() or not isinstance(usage, int) or usage <= 0:
            raise ValueError("NIM response lacks generated text or token evidence")
        return {"model": NIM_MODEL, "content": answer, "completion_tokens": usage,
                "backend": "nvidia-nim", "quotaNote": "No billing entitlement verification available"}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        # Do not return upstream exception text: some providers embed prompt or credentials.
        raise HTTPException(502, "NVIDIA NIM response unavailable or missing usage evidence") from exc
