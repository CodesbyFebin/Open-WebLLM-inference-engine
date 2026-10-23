import asyncio
import time
import httpx
from app.benchmarks import extract_event, measure, qualified, save_run

def test_usage_event():
    assert extract_event('{"choices":[{"text":"hello"}],"usage":{"completion_tokens":2}}') == ('hello',2)

def test_requires_three_real_samples(tmp_path):
    path=str(tmp_path/'bench.sqlite')
    for i in range(2):
        save_run(path,dict(backend='gpu',model='m',prompt_id='simple',passed=True,ttft_ms=3.,duration_ms=10.,completion_tokens=5,error=None,timestamp=time.time()))
    assert qualified(path,'gpu','m') is None
    save_run(path,dict(backend='gpu',model='m',prompt_id='simple',passed=False,ttft_ms=None,duration_ms=10.,completion_tokens=None,error='fail',timestamp=time.time()))
    assert qualified(path,'gpu','m') is None

def test_live_stream_protocol_with_mock_transport():
    def handle(request):
        assert request.url.path == '/v1/completions'
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text=(
            'data: {"choices":[{"text":"real sampled text"}]}\n\n'
            'data: {"choices":[],"usage":{"completion_tokens":3}}\n\n'
            'data: [DONE]\n\n'))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await measure(client,'http://test','demo','prompt','gpu','simple')
    result=asyncio.run(run())
    assert result['passed'] and result['completion_tokens']==3 and result['ttft_ms'] is not None
