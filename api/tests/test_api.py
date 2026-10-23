import os
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
