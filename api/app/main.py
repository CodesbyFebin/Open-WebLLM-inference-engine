import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from .routing import Backend, RouteOptions, decide
from .registry import registry

VLLM_URL = os.getenv('VLLM_URL', 'http://vllm:8000').rstrip('/')
VLLM_MODEL = os.getenv('VLLM_MODEL', 'Qwen/Qwen2.5-7B-Instruct')
API_KEY = os.getenv('API_KEY', '')
REQUESTS = Counter('gateway_inference_requests_total', 'Inference attempts', ['result'])
DURATION = Histogram('gateway_inference_duration_seconds', 'Inference latency')

@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10)) as client:
        app.state.http = client
        yield

app = FastAPI(title='Dual Inference Gateway', version='0.1.0', lifespan=lifespan)

class InferRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100000)
    model: str = VLLM_MODEL
    max_tokens: int = Field(default=128, ge=1, le=2048)
    temperature: float = Field(default=0.7, ge=0, le=2)
    stream: bool = False

def authorize(token):
    if not API_KEY or token != f'Bearer {API_KEY}':
        raise HTTPException(status_code=401, detail='Valid bearer token required')

@app.get('/health')
async def health():
    return {'status': 'ok', 'mode': 'gpu-proxy'}

@app.get('/api/models')
async def models(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return {'gpu': [{'name': VLLM_MODEL, 'backend': 'gpu'}],
            'runtimes': [vars(runtime) for runtime in registry(os.environ)]}

class RouteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=50000)
    privacy: str = 'standard'
    quality: str = 'balanced'
    preferred: str = 'auto'
    browser_available: bool = False

@app.post('/api/route')
async def route(req: RouteRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        target, reason = decide(req.prompt, RouteOptions(
            privacy=req.privacy, quality=req.quality, preferred=req.preferred,
            browser_available=req.browser_available,
            edge_available=bool(os.getenv('EDGE_URL')),
            gpu_available=bool(os.getenv('VLLM_URL'))))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'backend': target.value, 'reason': reason,
            'executeInBrowser': target == Backend.BROWSER,
            'apiEndpoint': '/api/infer' if target == Backend.GPU else None,
            'note': 'Routing decision only; no inference or model download occurred'}

@app.post('/api/infer')
async def infer(req: InferRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    if req.model != VLLM_MODEL:
        raise HTTPException(422, 'This endpoint only accepts the configured GPU model; WASM runs locally in the browser')
    payload = {'model': req.model, 'prompt': req.prompt, 'max_tokens': req.max_tokens,
               'temperature': req.temperature, 'stream': req.stream}
    started = time.perf_counter()
    if req.stream:
        async def events():
            try:
                async with app.state.http.stream('POST', f'{VLLM_URL}/v1/completions', json=payload) as upstream:
                    upstream.raise_for_status()
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                REQUESTS.labels('ok').inc()
            except httpx.HTTPError:
                REQUESTS.labels('error').inc()
                yield b'data: {"error":"GPU backend unavailable"}\n\n'
            finally:
                DURATION.observe(time.perf_counter()-started)
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control':'no-cache', 'X-Accel-Buffering':'no'})
    try:
        response = await app.state.http.post(f'{VLLM_URL}/v1/completions', json=payload)
        response.raise_for_status()
    except httpx.HTTPError:
        REQUESTS.labels('error').inc()
        raise HTTPException(502, 'GPU inference backend unavailable')
    finally:
        DURATION.observe(time.perf_counter()-started)
    REQUESTS.labels('ok').inc()
    return response.json()

def parse_metrics(raw: str):
    result = {}
    for line in raw.splitlines():
        if not line or line.startswith('#'):
            continue
        name, *rest = line.split(' ', 1)
        if not rest:
            continue
        metric = name.split('{', 1)[0]
        if metric in ('vllm:kv_cache_usage_perc', 'vllm:gpu_cache_usage_perc',
                      'vllm:prefix_cache_hits', 'vllm:prefix_cache_queries',
                      'vllm:gpu_prefix_cache_hit_rate'):
            try:
                result[metric] = float(rest[0].split()[0])
            except ValueError:
                pass
    return result

@app.get('/api/cache/status')
async def cache(authorization: str | None = Header(default=None)):
    authorize(authorization)
    try:
        r = await app.state.http.get(f'{VLLM_URL}/metrics')
        r.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(503, 'vLLM telemetry unavailable')
    metrics = parse_metrics(r.text)
    utilization = metrics.get('vllm:kv_cache_usage_perc', metrics.get('vllm:gpu_cache_usage_perc'))
    hits = metrics.get('vllm:prefix_cache_hits')
    queries = metrics.get('vllm:prefix_cache_queries')
    hit_rate = hits/queries if hits is not None and queries else metrics.get('vllm:gpu_prefix_cache_hit_rate')
    return {'source': 'vllm-prometheus', 'realAllocation': True, 'blockSize': 16,
            'utilization': utilization, 'prefixHitRate': hit_rate, 'blockTable': None,
            'note': 'vLLM does not expose individual physical block ownership through its public metrics API.'}

@app.get('/api/metrics')
async def metrics(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
