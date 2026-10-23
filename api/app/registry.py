"""Runtime adapters: advertised support is not evidence of local deployment."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Runtime:
    id: str
    task: str
    placement: str
    api: str
    configured: bool
    notes: str

def registry(env):
    return [
        Runtime('transformersjs', 'text-generation', 'browser', 'local-worker', True, 'q4f16 ONNX WebGPU; depends on client support'),
        Runtime('webllm', 'text-generation', 'browser', 'future-adapter', False, 'MLC artifacts are not ONNX models'),
        Runtime('vllm', 'text-generation', 'gpu', 'openai-completions', bool(env.get('VLLM_URL')), 'server-configured Qwen checkpoint'),
        Runtime('local-openai', 'text-generation', 'edge', 'openai-completions', bool(env.get('EDGE_URL')), 'operator-managed local service'),
        Runtime('comfyui', 'image-generation', 'gpu', 'comfy-prompt', False, 'workflow graph adapter pending'),
        Runtime('mnn', 'text-generation', 'mobile', 'native-sdk', False, 'requires native bindings and device testing'),
        Runtime('cactus', 'text-generation', 'mobile', 'native-sdk', False, 'requires native bindings and device testing'),
    ]
