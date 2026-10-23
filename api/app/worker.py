"""Durable, lease-based inference worker. No shell, plugin, or code execution."""
import asyncio
import json
import logging
import os
import socket
import time
import uuid

import httpx
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("hello.worker")


class InferenceWorker:
    def __init__(self, database_url: str, vllm_url: str, model: str, api_key: str = ""):
        self.worker_id = f"{socket.gethostname()}-{uuid.uuid4()}"
        self.pool = AsyncConnectionPool(database_url, min_size=1, max_size=2, open=False,
                                        kwargs={"row_factory": dict_row})
        self.vllm_url = vllm_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    async def start(self):
        await self.pool.open()
        await self.pool.wait()

    async def close(self):
        await self.pool.close()

    async def claim(self):
        async with self.pool.connection() as conn:
            return await (await conn.execute("SELECT * FROM hello_claim_job(%s,%s)",
                                             (self.worker_id, 180))).fetchone()

    async def mark_started(self, job_id: str):
        async with self.pool.connection() as conn:
            row = await (await conn.execute("SELECT hello_mark_job_started(%s,%s) AS accepted",
                                            (job_id, self.worker_id))).fetchone()
            return bool(row["accepted"])

    async def finish(self, job_id: str, result: dict | None, error: str | None):
        async with self.pool.connection() as conn:
            row = await (await conn.execute("SELECT hello_finish_job(%s,%s,%s,%s) AS accepted",
                                            (job_id, self.worker_id, Jsonb(result) if result is not None else None,
                                             error))).fetchone()
            return bool(row["accepted"])

    async def run_once(self, client: httpx.AsyncClient):
        job = await self.claim()
        if not job:
            return False
        job_id = str(job["job_id"])
        payload = job["payload"]
        if (job["kind"] != "inference" or payload.get("model") != self.model
                or not isinstance(payload.get("prompt"), str)
                or len(payload["prompt"]) > 10000
                or not isinstance(payload.get("max_tokens"), int)
                or not 1 <= payload["max_tokens"] <= 256):
            await self.finish(job_id, None, "terminal: invalid worker payload")
            return True
        # Persist the outbound boundary before calling the provider. If the
        # process dies after this point, the lease expires to FAILED rather
        # than repeating a potentially billable, non-idempotent inference.
        if not await self.mark_started(job_id):
            return True
        started = time.perf_counter()
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            response = await client.post(
                f"{self.vllm_url}/v1/completions", headers=headers,
                json={"model": self.model, "prompt": payload["prompt"],
                      "max_tokens": payload["max_tokens"], "temperature": 0, "stream": False},
                timeout=httpx.Timeout(120, connect=10),
            )
            response.raise_for_status()
            body = response.json()
            choices = body.get("choices") or []
            text = choices[0].get("text") if choices else None
            usage = (body.get("usage") or {}).get("completion_tokens")
            if not isinstance(text, str) or not text.strip() or not isinstance(usage, int) or not 0 < usage <= payload["max_tokens"]:
                raise ValueError("missing generated output or valid provider token usage")
            result = {"content": text, "completion_tokens": usage,
                      "model": self.model, "backend": "vllm",
                      "duration_ms": round((time.perf_counter()-started)*1000, 2)}
            accepted = await self.finish(job_id, result, None)
            if accepted:
                log.info("job succeeded job_id=%s completion_tokens=%s", job_id, usage)
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            # Provider text and response bodies are intentionally excluded from logs and audit.
            await self.finish(job_id, None, "inference backend request failed")
            log.warning("job failed; retry will follow bounded queue policy job_id=%s", job_id)
        return True

    async def run(self):
        await self.start()
        try:
            async with httpx.AsyncClient() as client:
                while True:
                    if not await self.run_once(client):
                        await asyncio.sleep(0.5)
        finally:
            await self.close()


async def main():
    database_url = os.getenv("WORKER_DATABASE_URL")
    vllm_url = os.getenv("VLLM_URL")
    if not database_url or not vllm_url:
        raise SystemExit("WORKER_DATABASE_URL and VLLM_URL are required")
    worker = InferenceWorker(database_url, vllm_url,
                             os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
                             os.getenv("VLLM_API_KEY", ""))
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
