"""Concurrent gateway load probe with a local transport; never calls a provider."""
import asyncio
import os

import httpx

os.environ["API_KEY"] = "test-key"
from app.main import app, VLLM_MODEL


def test_gateway_handles_concurrent_inference_requests_without_provider_calls():
    class LocalTransport:
        calls = 0
        async def post(self, url, **kwargs):
            self.calls += 1
            return httpx.Response(200, json={
                "choices": [{"text": "bounded local fixture output"}],
                "usage": {"completion_tokens": 4},
            }, request=httpx.Request("POST", url))

    async def run():
        app.state.store = None
        fake = LocalTransport()
        app.state.http = fake
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            results = await asyncio.gather(*[
                client.post("/api/infer", headers={"Authorization": "Bearer test-key"},
                            json={"prompt": f"request {index}", "model": VLLM_MODEL,
                                  "max_tokens": 8})
                for index in range(40)
            ])
        assert fake.calls == 40
        assert all(response.status_code == 200 for response in results)
        assert all(response.json()["usage"]["completion_tokens"] == 4 for response in results)

    asyncio.run(run())
