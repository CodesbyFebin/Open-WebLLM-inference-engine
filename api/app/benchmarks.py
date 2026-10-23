"""Measured OpenAI-compatible backend qualification; no synthetic completions."""
import json
import os
import sqlite3
import time
from pathlib import Path

import httpx

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 backend TEXT NOT NULL, model TEXT NOT NULL, prompt_id TEXT NOT NULL,
 passed INTEGER NOT NULL, ttft_ms REAL, duration_ms REAL NOT NULL,
 completion_tokens INTEGER, error TEXT, timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_backend_time ON runs(backend,model,timestamp);
"""
DEFAULT_CASES = (
    ('simple', 'In exactly one sentence, explain what a CPU is.'),
    ('reasoning', 'Explain the tradeoffs between paging and contiguous memory allocation in three points.'),
    ('code', 'Write a Python function that returns a list in reverse order without changing its input.'),
)

def _database(path: str):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db

def save_run(path: str, row: dict):
    with _database(path) as db:
        db.execute('INSERT INTO runs(backend,model,prompt_id,passed,ttft_ms,duration_ms,completion_tokens,error,timestamp) VALUES(?,?,?,?,?,?,?,?,?)',
                   (row['backend'], row['model'], row['prompt_id'], int(row['passed']), row['ttft_ms'],
                    row['duration_ms'], row['completion_tokens'], row['error'], row['timestamp']))

def qualified(path: str, backend: str, model: str, min_passes=3, ttl_seconds=86400):
    if not Path(path).is_file():
        return None
    with _database(path) as db:
        rows = db.execute('SELECT prompt_id,passed,ttft_ms,duration_ms,completion_tokens FROM runs WHERE backend=? AND model=? AND timestamp>=? ORDER BY id DESC LIMIT ?',
                          (backend, model, time.time()-ttl_seconds, min_passes)).fetchall()
    if len(rows)<min_passes or len({row[0] for row in rows})<min_passes or not all(row[1] and row[2] is not None and row[4]>0 for row in rows):
        return None
    return {'backend':backend,'model':model,'sampleCount':len(rows),
            'medianTtftMs':sorted(row[2] for row in rows)[len(rows)//2],
            'medianDurationMs':sorted(row[3] for row in rows)[len(rows)//2],
            'verified':True}

def extract_event(payload: str):
    """Return decoded content and completion tokens from one SSE JSON event."""
    try:
        event=json.loads(payload)
    except json.JSONDecodeError:
        return '', None
    choices=event.get('choices') or []
    text=''.join(str(c.get('text') or c.get('delta',{}).get('content') or '') for c in choices)
    usage=event.get('usage') or {}
    tokens=usage.get('completion_tokens')
    return text, tokens if isinstance(tokens,int) and tokens>0 else None

async def measure(client: httpx.AsyncClient, url: str, model: str, prompt: str, backend: str, prompt_id: str, key: str=''):
    """One actual streaming request. Fail if no sampled text or usage evidence."""
    started=time.perf_counter()
    result={'backend':backend,'model':model,'prompt_id':prompt_id,'passed':False,'ttft_ms':None,
            'duration_ms':0.,'completion_tokens':None,'error':None,'timestamp':time.time()}
    try:
        headers={'Authorization':f'Bearer {key}'} if key else {}
        async with client.stream('POST',f'{url.rstrip("/")}/v1/completions',headers=headers,
             json={'model':model,'prompt':prompt,'max_tokens':96,'temperature':0,'stream':True,
                   'stream_options':{'include_usage':True}},timeout=120) as response:
            response.raise_for_status()
            text_parts=[]
            async for line in response.aiter_lines():
                if not line.startswith('data: '):
                    continue
                payload=line[6:].strip()
                if payload=='[DONE]':
                    break
                text,tokens=extract_event(payload)
                if text:
                    text_parts.append(text)
                    if result['ttft_ms'] is None:
                        result['ttft_ms']=(time.perf_counter()-started)*1000
                if tokens is not None:
                    result['completion_tokens']=tokens
            if not ''.join(text_parts).strip():
                raise ValueError('No real generated output received')
            if result['completion_tokens'] is None:
                raise ValueError('Backend omitted completion token usage')
            result['passed']=True
    except (httpx.HTTPError,ValueError) as exc:
        result['error']=str(exc)[:300]
    result['duration_ms']=(time.perf_counter()-started)*1000
    return result

def configured_backends():
    results=[]
    if os.getenv('VLLM_URL'):
        results.append(('gpu',os.environ['VLLM_URL'],os.getenv('VLLM_MODEL','Qwen/Qwen2.5-7B-Instruct'),os.getenv('VLLM_API_KEY','')))
    if os.getenv('EDGE_URL'):
        results.append(('edge',os.environ['EDGE_URL'],os.getenv('EDGE_MODEL','local'),os.getenv('EDGE_API_KEY','')))
    return results
