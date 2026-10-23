import os
import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient

os.environ["API_KEY"] = "test-key"
from app.main import app
from app import nim

AUTH = {"Authorization": "Bearer test-key"}

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NIM_ENABLED", raising=False)
    monkeypatch.setenv("NIM_FREE_QUOTA_ACK", "I CONFIRM FREE ONLY")
    monkeypatch.setenv("NVIDIA_API_KEY", "unit-test-only")
    monkeypatch.setenv("NIM_MAX_REQUESTS", "3")
    with TestClient(app) as client:
        assert client.get("/api/nim/status", headers=AUTH).json()["enabled"] is False
        assert client.post("/api/nim/complete", headers=AUTH, json={"prompt": "hi"}).status_code == 503

def test_authentication_and_request_validation():
    with TestClient(app) as client:
        assert client.post("/api/nim/complete", json={"prompt": "hi"}).status_code == 401
        assert client.post("/api/nim/complete", headers=AUTH,
                           json={"prompt": "hi", "max_tokens": 49}).status_code == 422

def test_authenticated_nim_api_route_uses_bounded_adapter(monkeypatch):
    monkeypatch.setenv("NIM_ENABLED", "true")
    monkeypatch.setenv("NIM_FREE_QUOTA_ACK", "I CONFIRM FREE ONLY")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setenv("NIM_MAX_REQUESTS", "1")
    monkeypatch.setattr(nim, "_request_count", 0)

    class MockClient:
        async def post(self, url, **kwargs):
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "NIM answer"}}],
                "usage": {"completion_tokens": 2},
            }, request=httpx.Request("POST", url))

    with TestClient(app) as client:
        app.state.http = MockClient()
        response = client.post("/api/nim/complete", headers=AUTH,
                               json={"prompt": "hello", "max_tokens": 8})
        assert response.status_code == 200
        assert response.json()["backend"] == "nvidia-nim"
        assert response.json()["content"] == "NIM answer"
        assert response.json()["completion_tokens"] == 2
    monkeypatch.setattr(nim, "_request_count", 0)

def test_approved_bounded_request_and_exhaustion(monkeypatch):
    asyncio.run(_approved_bounded_request_and_exhaustion(monkeypatch))

async def _approved_bounded_request_and_exhaustion(monkeypatch):
    monkeypatch.setenv("NIM_ENABLED", "true")
    monkeypatch.setenv("NIM_FREE_QUOTA_ACK", "I CONFIRM FREE ONLY")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setenv("NIM_MAX_REQUESTS", "1")
    monkeypatch.setattr(nim, "_request_count", 0)
    seen = []
    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}],
                                          "usage": {"completion_tokens": 1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await nim.complete(client, "hello", 8)
        assert result["completion_tokens"] == 1
        assert seen[0].url == httpx.URL(nim.NIM_ENDPOINT)
        assert seen[0].headers["Authorization"] == "Bearer test-key-not-real"
        with pytest.raises(Exception) as exc:
            await nim.complete(client, "again", 8)
        assert exc.value.status_code == 429
    monkeypatch.setattr(nim, "_request_count", 0)

def test_no_unbounded_retry_on_upstream_failure(monkeypatch):
    asyncio.run(_no_unbounded_retry_on_upstream_failure(monkeypatch))

async def _no_unbounded_retry_on_upstream_failure(monkeypatch):
    monkeypatch.setenv("NIM_ENABLED", "true")
    monkeypatch.setenv("NIM_FREE_QUOTA_ACK", "I CONFIRM FREE ONLY")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setenv("NIM_MAX_REQUESTS", "1")
    monkeypatch.setattr(nim, "_request_count", 0)
    count = []
    def handler(req):
        count.append(1)
        return httpx.Response(429, json={"error": "quota exceeded"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(Exception) as exc:
            await nim.complete(client, "hello")
        assert exc.value.status_code == 502
    assert len(count) == 1
    monkeypatch.setattr(nim, "_request_count", 0)
