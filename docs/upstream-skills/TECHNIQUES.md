# Techniques worth keeping

Cloned 50 repositories at depth 1 on 2026-10-23. This file is the merge. It is not a copy of their source. Apache-2.0 and MIT notes stay in `notes/`. Do not vendor ComfyUI-style GPL trees, and do not treat a README claim as a measurement.

The Jules console already runs q4f16 ONNX on this CPU process and can use WebGPU only when the tab reports an adapter. These techniques fit that boundary.

## 1. Fail closed on the device

From `webgpu/webgpu-samples`, `webgpu/webgpufundamentals`, `pygfx/wgpu-py`, and `webgpu-native/webgpu-headers`.

- Ask for `navigator.gpu.requestAdapter()` and then `requestDevice()`. If either is missing, stay on the CPU path. Do not draw a GPU heatmap.
- Listen for `device.lost` and surface the reason. The Three.js WebGPU skill in `dgreenheck/webgpu-claude-skill` treats device loss as a first-class state, not a silent retry.
- Feature-detect WASM the same way `GoogleChromeLabs/wasm-feature-detect` does: simd, threads, bulk-memory, relaxed-simd, streaming compilation. A q4f16 ONNX build that needs threads must say so before download.

## 2. Keep weights honest

From `hamzaydia/verifyfetch` and `GoogleChromeLabs/squoosh`.

- A multi-hundred-megabyte weight download must resume and hash every byte. VerifyFetch is the pattern: range resume plus a digest, not a second full GET after a drop at 3.8 GB.
- Squoosh runs codecs in workers and never uploads the file. The same split belongs here: the UI thread owns the prompt, a worker owns the ONNX session, and the server path is a different process. Do not pretend they share a KV cache.

## 3. One worker protocol

From `GoogleChromeLabs/comlink` and `GoogleChromeLabs/clooney`.

- Comlink is the small version: `expose(api, port)` in the worker, `wrap(worker)` in the page, transfer `ArrayBuffer`s instead of cloning them.
- Clooney is the larger version: an actor pool that hides which worker is busy. Use it only if more than one model session runs at once. One SmolLM session does not need a pool.
- Cancellation is an `AbortSignal`, not a killed worker. A killed worker drops the loaded weights.

## 4. Two browser model formats, not one

From `GoogleChromeLabs/web-ai-demos`, `jakobhoeg/browser-ai`, `cfahlgren1/webllm-playground`, and `Ryan-yang125/ChatLLM-Web`.

- Transformers.js speaks ONNX. WebLLM speaks MLC artifacts. They are not interchangeable checkpoints. `@browser-ai/transformers-js` and `@browser-ai/web-llm` are separate providers with a shared AI SDK shape and an explicit server fallback.
- Chrome built-in Prompt, Summarizer, and embedder APIs are a third runtime. Detect them. Do not polyfill a result.
- ChatLLM-Web shows the studio shape that is already close to this console: a catalog, a local session, and agent tools only for models that actually expose them. A 135M ONNX checkpoint is not an agent.

## 5. Voice and page tools stay outside the sampler

From `activated-intelligence/voice-chat`, `YuriCrystal/ai-avatar-bot`, `GoogleChromeLabs/webmcp-tools`, and `RunanywhereAI/on-device-browser-agent`.

- A full local voice loop is Whisper plus a VAD plus a small WebLLM plus a TTS model. That is a separate download budget. The voice-chat repo is explicit that the LLM is swappable and the speech pipeline is the product.
- WebMCP registers tools on `document.modelContext` inside the page. It is not a backend MCP server and it is not DOM clicking. Tool names stay under 30 characters, descriptions say what and when, and the tool must not ask the model to do arithmetic the page can do.
- Nanobrowser-style page agents drive the browser from an extension. That is a different trust boundary from this inference console. Do not merge it into the sampler.

## 6. Native WebGPU is not this page

From `wcandillon/react-native-webgpu`, `playcanvas/engine`, and `Scthe/nanite-webgpu`.

- React Native WebGPU binds Dawn. It does not make a phone run the browser ONNX build.
- PlayCanvas is a WebGL2/WebGPU scene graph. Useful later for a KV visualization that is actually a texture. Not a model runtime.
- Nanite-WebGPU shows meshlet culling and a software raster fallback when the GPU path cannot cover the triangle. The lesson for us is the fallback, not the renderer: if WebGPU cannot do the op, say so and use the CPU session.

## 7. What was cloned and deliberately not merged

Identity, ads, and device demos are real projects and the wrong layer:

- `project-sesame`, `passkey-skills-demo`: passkeys. Do not add a login wall to this preview.
- `protected-audience-demo`, `shared-storage-demo`, `private-state-token-demo`: browser privacy experiments, not model privacy. Sensitive prompts still fail closed in `/v1/gate`.
- `paymentrequest-show`, `web-based-payment-app-example`, `rowing-monitor`, `serial-terminal`, `telnet-client`, `chromeos_smart_card_connector`, `web-audio-samples`: hardware and payment demos.
- `chrome-for-testing`, `chromium-bidi`, `webdriver-bidi-protocol`, `jsvu`: how to pin a browser and a JS engine for tests. Useful for CI later. Not an inference backend.
- `squoosh` codecs, `playcanvas` engine source, and Nanite assets stay in the clones. They are not in this zip.

## 8. Order to apply them here

1. WASM feature detect before the first weight fetch.
2. Resumable verified download for any checkpoint over the SmolLM2-135M already cached.
3. Comlink between the page and the existing WebGPU worker, with explicit transfer of token buffers.
4. Keep WebLLM as a separate adapter until an MLC manifest is loaded in this browser. Do not mark it live.
5. Expose Generate, Stop, and Switch checkpoint as WebMCP tools only after the gate can describe them in one sentence each.
