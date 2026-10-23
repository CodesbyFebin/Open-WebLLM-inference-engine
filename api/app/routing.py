"""Capability-aware inference routing. Browser execution is delegated, never faked."""
from dataclasses import dataclass
from enum import Enum

class Backend(str, Enum):
    BROWSER = 'browser'
    EDGE = 'edge'
    GPU = 'gpu'

@dataclass(frozen=True)
class RouteOptions:
    privacy: str = 'standard'
    quality: str = 'balanced'
    preferred: str = 'auto'
    browser_available: bool = False
    edge_available: bool = False
    gpu_available: bool = False

def decide(prompt: str, options: RouteOptions) -> tuple[Backend, str]:
    if options.privacy not in ('standard', 'sensitive'):
        raise ValueError('Unknown privacy policy')
    available = {Backend.BROWSER: options.browser_available,
                 Backend.EDGE: options.edge_available, Backend.GPU: options.gpu_available}
    if options.privacy == 'sensitive':
        for target in (Backend.EDGE, Backend.BROWSER):
            if available[target]:
                return target, 'sensitive data confined to local execution'
        raise ValueError('No private runtime available; GPU fallback forbidden')
    if options.preferred != 'auto':
        try:
            target = Backend(options.preferred)
        except ValueError as exc:
            raise ValueError('Unknown requested backend') from exc
        if not available[target]:
            raise ValueError('Requested backend unavailable')
        return target, 'explicit user preference'
    complex_task = len(prompt.split()) > 170 or any(
        term in prompt.lower() for term in ('architecture', 'refactor', 'reasoning', 'security audit'))
    if (complex_task or options.quality == 'accurate') and available[Backend.GPU]:
        return Backend.GPU, 'task complexity and quality'
    for target in (Backend.BROWSER, Backend.EDGE, Backend.GPU):
        if available[target]:
            return target, 'available compatible runtime'
    raise ValueError('No backend available')
