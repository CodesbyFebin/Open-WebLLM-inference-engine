import hmac
import json
import os
import time
from contextlib import asynccontextmanager

import httpx
import psycopg
from psycopg.errors import UniqueViolation
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from .identity import ADMIN_ROLES, INFERENCE_ROLES, Principal, require_role
from .routing import Backend, RouteOptions, decide
from .registry import registry
from .benchmarks import DEFAULT_CASES, configured_backends, measure, qualified, save_run
from .nim import complete as nim_complete, readiness as nim_readiness
from .store import PostgresStore

VLLM_URL = os.getenv('VLLM_URL', 'http://vllm:8000').rstrip('/')
VLLM_MODEL = os.getenv('VLLM_MODEL', 'Qwen/Qwen2.5-7B-Instruct')
API_KEY = os.getenv('API_KEY', '')
REQUESTS = Counter('gateway_inference_requests_total', 'Inference attempts', ['result'])
DURATION = Histogram('gateway_inference_duration_seconds', 'Inference latency')

@asynccontextmanager
async def lifespan(app):
    store = None
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        if os.getenv('APP_ENV') == 'production' and len(os.getenv('AUTH_THROTTLE_PEPPER', '')) < 32:
            raise RuntimeError('AUTH_THROTTLE_PEPPER with at least 32 characters is required in production')
        store = PostgresStore(database_url)
        await store.open()
    elif os.getenv('APP_ENV') == 'production':
        raise RuntimeError('DATABASE_URL is required when APP_ENV=production')
    app.state.store = store
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10)) as client:
            app.state.http = client
            yield
    finally:
        if store:
            await store.close()

app = FastAPI(title='Dual Inference Gateway', version='0.1.0', lifespan=lifespan)

class InferRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100000)
    model: str = VLLM_MODEL
    max_tokens: int = Field(default=128, ge=1, le=2048)
    temperature: float = Field(default=0.7, ge=0, le=2)
    stream: bool = False

async def authorize(token):
    if token and token.startswith('Bearer '):
        value = token[7:]
        store = getattr(app.state, 'store', None)
        if store:
            principal = await store.resolve(value)
            if principal:
                return principal
        if API_KEY and (not store or os.getenv('ALLOW_MACHINE_API_KEY') == 'true') and hmac.compare_digest(value, API_KEY):
            return Principal(None, None, 'admin', 'machine')
    raise HTTPException(status_code=401, detail='Valid session bearer token required')

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)

class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(default='member', pattern='^(admin|member|viewer)$')

@app.post('/api/auth/session')
async def create_session(req: LoginRequest, request: Request):
    store = getattr(app.state, 'store', None)
    if not store:
        raise HTTPException(503, 'Database-backed accounts are not configured')
    client_ip = request.client.host if request.client else 'unknown'
    return await store.login(req.email, req.password, client_ip)

@app.get('/api/auth/me')
async def current_session(authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    return {'userId': principal.user_id, 'tenantId': principal.tenant_id,
            'role': principal.role, 'authKind': principal.auth_kind}

@app.delete('/api/auth/session')
async def revoke_session(authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    if principal.auth_kind != 'session':
        raise HTTPException(422, 'Only session tokens can be revoked here')
    await app.state.store.revoke(principal, authorization[7:])
    return {'revoked': True}

@app.get('/api/usage')
async def tenant_usage(authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    if not app.state.store or not principal.tenant_id:
        raise HTTPException(503, 'Tenant usage requires database-backed account authentication')
    return await app.state.store.usage(principal)

@app.get('/api/audit')
async def tenant_audit(limit: int = 100, authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, ADMIN_ROLES)
    if not app.state.store or not principal.tenant_id:
        raise HTTPException(503, 'Audit history requires database-backed account authentication')
    return {'events': await app.state.store.list_audit(principal, max(1, min(limit, 500)))}

@app.post('/api/admin/users', status_code=201)
async def provision_user(req: CreateUserRequest, authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, ADMIN_ROLES)
    if not app.state.store or not principal.tenant_id:
        raise HTTPException(503, 'User provisioning requires database-backed tenant authentication')
    if '@' not in req.email or req.email.startswith('@') or req.email.endswith('@'):
        raise HTTPException(422, 'A valid email address is required')
    if principal.role == 'admin' and req.role == 'admin':
        raise HTTPException(403, 'Only a tenant owner may provision administrators')
    try:
        return await app.state.store.create_user(principal.tenant_id, req.email,
                                                 req.password, req.role, principal.user_id)
    except UniqueViolation as exc:
        raise HTTPException(409, 'An account with this email already exists') from exc
    except psycopg.Error as exc:
        raise HTTPException(503, 'Account provisioning database unavailable') from exc

@app.get('/health')
async def health():
    return {'status': 'ok', 'mode': 'inference-gateway'}

@app.get('/ready')
async def ready():
    store = getattr(app.state, 'store', None)
    if os.getenv('APP_ENV') == 'production' and not store:
        raise HTTPException(503, 'Database-backed production mode is not ready')
    if store:
        try:
            await store.ping()
        except Exception as exc:
            raise HTTPException(503, 'Database is not ready') from exc
    return {'ready': True, 'database': 'connected' if store else 'local-key-mode'}

class NimRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    max_tokens: int = Field(default=48, ge=1, le=48)

@app.get('/api/nim/status')
async def nim_status(authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    return nim_readiness()

@app.post('/api/nim/complete')
async def nim_infer(req: NimRequest, authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, INFERENCE_ROLES)
    store = app.state.store
    reservation = await store.reserve_inference(principal, req.max_tokens, nim_readiness()['model']) if store else None
    try:
        result = await nim_complete(app.state.http, req.prompt, req.max_tokens)
        if result['completion_tokens'] > req.max_tokens:
            raise HTTPException(502, 'NVIDIA NIM returned usage above the requested token cap')
        if store:
            await store.finish_inference(principal, reservation, result['completion_tokens'], True)
        return result
    except HTTPException:
        if store:
            await store.finish_inference(principal, reservation, 0, False)
        raise

@app.get('/api/models')
async def models(authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
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
    principal = await authorize(authorization)
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

class JobRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    max_tokens: int = Field(default=96, ge=1, le=256)

@app.post('/api/jobs', status_code=202)
async def submit_job(req: JobRequest, authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, INFERENCE_ROLES)
    store = app.state.store
    if not store or not principal.tenant_id:
        raise HTTPException(503, 'Durable jobs require database-backed tenant authentication')
    if not os.getenv('VLLM_URL'):
        raise HTTPException(503, 'No worker inference backend is configured')
    reservation = await store.reserve_inference(principal, req.max_tokens, VLLM_MODEL)
    try:
        job_id = await store.enqueue_job(principal,
                                         {'prompt': req.prompt, 'model': VLLM_MODEL,
                                          'max_tokens': req.max_tokens}, reservation)
    except Exception:
        await store.finish_inference(principal, reservation, 0, False)
        raise
    return {'jobId': job_id, 'status': 'queued', 'pollUrl': f'/api/jobs/{job_id}'}

@app.get('/api/jobs/{job_id}')
async def job_status(job_id: str, authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, INFERENCE_ROLES)
    if not app.state.store or not principal.tenant_id:
        raise HTTPException(503, 'Durable jobs require database-backed tenant authentication')
    job = await app.state.store.get_job(principal, job_id)
    if not job:
        raise HTTPException(404, 'Job not found')
    return job

@app.delete('/api/jobs/{job_id}')
async def cancel_job(job_id: str, authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, INFERENCE_ROLES)
    if not app.state.store or not principal.tenant_id:
        raise HTTPException(503, 'Durable jobs require database-backed tenant authentication')
    if not await app.state.store.cancel_job(principal, job_id):
        raise HTTPException(409, 'Only queued jobs can be cancelled')
    return {'jobId': job_id, 'status': 'cancelled'}

@app.post('/api/benchmarks/run')
async def run_benchmarks(req: BenchmarkRequest, authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, ADMIN_ROLES)
    candidate = next((item for item in configured_backends() if item[0] == req.backend), None)
    if candidate is None:
        raise HTTPException(422, 'Backend not configured or not eligible for this text benchmark')
    backend, url, model, secret = candidate
    # This endpoint intentionally executes real model requests and can incur GPU cost.
    path = os.getenv('BENCHMARK_DB', '/tmp/inference-benchmarks.sqlite3')
    results = []
    for _ in range(req.repetitions):
        for prompt_id, prompt in DEFAULT_CASES:
            reservation = await app.state.store.reserve_inference(principal, 96, model) if app.state.store else None
            row = await measure(app.state.http, url, model, prompt, backend, prompt_id, secret)
            if app.state.store:
                await app.state.store.finish_inference(principal, reservation,
                                                       row['completion_tokens'] or 0,
                                                       bool(row['passed'] and row['completion_tokens'] <= 96))
            save_run(path, row)
            results.append(row)
    return {'results': results, 'qualification': qualified(path, backend, model)}

@app.get('/api/benchmarks/status')
async def benchmark_status(authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, ADMIN_ROLES)
    path = os.getenv('BENCHMARK_DB', '/tmp/inference-benchmarks.sqlite3')
    return {'backends': [{'backend': backend, 'model': model,
                          'qualification': qualified(path, backend, model)}
                         for backend, _, model, _ in configured_backends()],
            'browser': {'qualification': None, 'reason': 'Browser measurements are not server-attested'}}

@app.post('/api/infer')
async def infer(req: InferRequest, authorization: str | None = Header(default=None)):
    principal = await authorize(authorization)
    require_role(principal, INFERENCE_ROLES)
    if req.model != VLLM_MODEL:
        raise HTTPException(422, 'This endpoint only accepts the configured GPU model; WASM runs locally in the browser')
    payload = {'model': req.model, 'prompt': req.prompt, 'max_tokens': req.max_tokens,
               'temperature': req.temperature, 'stream': req.stream}
    started = time.perf_counter()
    store = app.state.store
    reservation = await store.reserve_inference(principal, req.max_tokens, req.model) if store else None
    if req.stream:
        async def events():
            succeeded = False
            actual_tokens = None
            has_text = False
            try:
                async with app.state.http.stream('POST', f'{VLLM_URL}/v1/completions', json=payload) as upstream:
                    upstream.raise_for_status()
                    async for line in upstream.aiter_lines():
                        if line.startswith('data: '):
                            data = line[6:].strip()
                            if data != '[DONE]':
                                try:
                                    event = json.loads(data)
                                    choices = event.get('choices') or []
                                    has_text = has_text or any(choice.get('text') or choice.get('delta', {}).get('content') for choice in choices)
                                    tokens = (event.get('usage') or {}).get('completion_tokens')
                                    if isinstance(tokens, int):
                                        actual_tokens = tokens
                                except (json.JSONDecodeError, AttributeError, TypeError):
                                    pass
                        yield (line + '\n').encode()
                    succeeded = has_text and actual_tokens is not None and 0 < actual_tokens <= req.max_tokens
                    if not succeeded:
                        yield b'data: {"error":"GPU backend omitted valid output or token usage"}\n\n'
                REQUESTS.labels('ok' if succeeded else 'error').inc()
            except httpx.HTTPStatusError:
                REQUESTS.labels('error').inc()
                yield b'data: {"error":"GPU backend rejected or limited the request"}\n\n'
            except httpx.HTTPError:
                REQUESTS.labels('error').inc()
                yield b'data: {"error":"GPU backend unavailable"}\n\n'
            finally:
                if store:
                    await store.finish_inference(principal, reservation, actual_tokens or 0, succeeded)
                DURATION.observe(time.perf_counter()-started)
        return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control':'no-cache', 'X-Accel-Buffering':'no'})
    try:
        response = await app.state.http.post(f'{VLLM_URL}/v1/completions', json=payload)
        response.raise_for_status()
        body = response.json()
        choices = body.get('choices') or []
        completion_text = choices[0].get('text') if choices else None
        completion_tokens = (body.get('usage') or {}).get('completion_tokens')
        if not isinstance(completion_text, str) or not completion_text.strip() or not isinstance(completion_tokens, int) or not 0 < completion_tokens <= req.max_tokens:
            raise HTTPException(502, 'GPU backend omitted valid output or token usage')
        if store:
            await store.finish_inference(principal, reservation, completion_tokens, True)
    except httpx.HTTPStatusError as exc:
        if store:
            await store.finish_inference(principal, reservation, 0, False)
        REQUESTS.labels('error').inc()
        if exc.response.status_code == 429:
            retry = exc.response.headers.get('Retry-After')
            headers = {'Retry-After': retry} if retry and retry.isdigit() else None
            raise HTTPException(429, 'GPU backend rate limited the request; no automatic retry was attempted', headers=headers)
        raise HTTPException(502, 'GPU inference backend unavailable')
    except httpx.HTTPError:
        if store:
            await store.finish_inference(principal, reservation, 0, False)
        REQUESTS.labels('error').inc()
        raise HTTPException(502, 'GPU inference backend unavailable')
    except HTTPException:
        if store:
            await store.finish_inference(principal, reservation, 0, False)
        REQUESTS.labels('error').inc()
        raise
    finally:
        DURATION.observe(time.perf_counter()-started)
    REQUESTS.labels('ok').inc()
    return body

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
    principal = await authorize(authorization)
    require_role(principal, ADMIN_ROLES)
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
    principal = await authorize(authorization)
    require_role(principal, ADMIN_ROLES)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
