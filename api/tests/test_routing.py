import pytest
from app.routing import Backend, RouteOptions, decide

def test_simple_prefers_browser():
    assert decide('hello', RouteOptions(browser_available=True, gpu_available=True))[0] == Backend.BROWSER

def test_complex_prefers_gpu():
    assert decide('review this architecture', RouteOptions(browser_available=True, gpu_available=True))[0] == Backend.GPU

def test_private_fail_closed():
    with pytest.raises(ValueError, match='private'):
        decide('private record', RouteOptions(privacy='sensitive', gpu_available=True))

def test_private_edge():
    assert decide('private record', RouteOptions(privacy='sensitive', edge_available=True, gpu_available=True))[0] == Backend.EDGE
