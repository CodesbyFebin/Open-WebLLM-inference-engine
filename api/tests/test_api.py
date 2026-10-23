import os
import httpx
os.environ['API_KEY'] = 'test-key'
from fastapi.testclient import TestClient
from app.main import app, parse_metrics

def test_auth_required():
    with TestClient(app) as c:
        assert c.get('/api/models').status_code == 401
        assert c.get('/api/models', headers={'Authorization':'Bearer test-key'}).status_code == 200

def test_disallow_browser_model_through_server():
    with TestClient(app) as c:
        r = c.post('/api/infer', headers={'Authorization':'Bearer test-key'},
                   json={'prompt':'hello', 'model':'browser'})
        assert r.status_code == 422

def test_metrics_parser():
    parsed = parse_metrics('vllm:kv_cache_usage_perc{engine="0"} 0.25\nvllm:prefix_cache_hits 32\n')
    assert parsed['vllm:kv_cache_usage_perc'] == .25
    assert parsed['vllm:prefix_cache_hits'] == 32

def test_rate_limit_is_propagated_without_retry_or_provider_body_leak():
    class LimitedGateway:
        calls = 0
        async def post(self, url, **kwargs):
            self.calls += 1
            return httpx.Response(429, headers={'Retry-After':'7'},
                                  json={'error':'provider body should not be exposed'},
                                  request=httpx.Request('POST', url))
    with TestClient(app) as c:
        fake = LimitedGateway()
        app.state.http = fake
        r = c.post('/api/infer', headers={'Authorization':'Bearer test-key'},
                   json={'prompt':'hello','model':'Qwen/Qwen2.5-7B-Instruct'})
        assert r.status_code == 429
        assert r.headers['retry-after'] == '7'
        assert 'provider body' not in r.text
        assert fake.calls == 1
