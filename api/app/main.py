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
from .benchmarks import DEFAULT_CASES, configured_backends, measure, qualified, save_run
from .nim import complete as nim_complete, readiness as nim_readiness

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

class NimRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    max_tokens: int = Field(default=48, ge=1, le=48)

@app.get('/api/nim/status')
async def nim_status(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return nim_readiness()

@app.post('/api/nim/complete')
async def nim_infer(req: NimRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    return await nim_complete(app.state.http, req.prompt, req.max_tokens)

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
    candidates = configured_backends()
    path = os.getenv('BENCHMARK_DB', '/tmp/inference-benchmarks.sqlite3')
    verified = {backend: q for backend, _, model, _ in candidates
                if (q := qualified(path, backend, model)) is not None}
    try:
        target, reason = decide(req.prompt, RouteOptions(
            privacy=req.privacy, quality=req.quality, preferred=req.preferred,
            browser_available=req.browser_available if req.preferred != 'auto' else False,
            edge_available=('edge' in verified) if req.preferred == 'auto' else bool(os.getenv('EDGE_URL')),
            gpu_available=('gpu' in verified) if req.preferred == 'auto' else bool(os.getenv('VLLM_URL'))))
    except ValueError as exc:
        raise HTTPException(503 if req.preferred == 'auto' else 422, str(exc)) from exc
    if req.preferred == 'auto' and req.privacy != 'sensitive' and req.quality != 'accurate' and len(verified) > 1:
        winner = min(verified.values(), key=lambda q: q['medianDurationMs'])
        target = Backend(winner['backend'])
        reason = 'Fastest qualified backend by median measured duration'
    qualification = None
    if target in (Backend.GPU, Backend.EDGE) and req.preferred == 'auto':
        candidate = next((item for item in candidates if item[0] == target.value), None)
        if not candidate:
            raise HTTPException(503, 'Selected runtime has no configured adapter')
        qualification = verified.get(target.value)
        if not qualification:
            raise HTTPException(503, 'Runtime has no fresh passing benchmark evidence; automatic routing disabled')
    return {'backend': target.value, 'reason': reason,
            'executeInBrowser': target == Backend.BROWSER,
            'apiEndpoint': '/api/infer' if target == Backend.GPU else None,
            'qualification': qualification,
            'note': 'Routing decision only; no inference or model download occurred'}

class BenchmarkRequest(BaseModel):
    backend: str
    repetitions: int = Field(default=1, ge=1, le=3)

@app.post('/api/benchmarks/run')
async def run_benchmarks(req: BenchmarkRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    candidate = next((item for item in configured_backends() if item[0] == req.backend), None)
    if candidate is None:
        raise HTTPException(422, 'Backend not configured or not eligible for this text benchmark')
    backend, url, model, secret = candidate
    # This endpoint intentionally executes real model requests and can incur GPU cost.
    path = os.getenv('BENCHMARK_DB', '/tmp/inference-benchmarks.sqlite3')
    results = []
    for _ in range(req.repetitions):
        for prompt_id, prompt in DEFAULT_CASES:
            row = await measure(app.state.http, url, model, prompt, backend, prompt_id, secret)
            save_run(path, row)
            results.append(row)
    return {'results': results, 'qualification': qualified(path, backend, model)}

@app.get('/api/benchmarks/status')
async def benchmark_status(authorization: str | None = Header(default=None)):
    authorize(authorization)
    path = os.getenv('BENCHMARK_DB', '/tmp/inference-benchmarks.sqlite3')
    return {'backends': [{'backend': backend, 'model': model,
                          'qualification': qualified(path, backend, model)}
                         for backend, _, model, _ in configured_backends()],
            'browser': {'qualification': None, 'reason': 'Browser measurements are not server-attested'}}

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
