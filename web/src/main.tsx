import React,{useEffect,useRef,useState} from 'react';
import{createRoot}from'react-dom/client';
import{models,blockTable}from'./models';
import './style.css';
const WORKER = new URL('./inference.worker.ts',import.meta.url);
function App(){
 const [model,setModel]=useState(models[0]);const [prompt,setPrompt]=useState('Explain prefix caching in simple terms.');
 const [output,setOutput]=useState('');const [status,setStatus]=useState('Idle');const [busy,setBusy]=useState(false);
 const [promptTokens,setPromptTokens]=useState(0);const [generated,setGenerated]=useState(0);
 const [ttft,setTtft]=useState<number|null>(null);const [elapsed,setElapsed]=useState(0);
 const [previous,setPrevious]=useState<string[]>([]);const [cache,setCache]=useState<any>(null);
 const [browserBench,setBrowserBench]=useState<{ttftMs:number|null;throughputTokPerSec:number;completionTokens:number;passed:boolean}|null>(null);
 const [key,setKey]=useState('');const [progress,setProgress]=useState(0);
 const worker=useRef<Worker|null>(null);const started=useRef(0);const first=useRef(false);
 useEffect(()=>{const w=new Worker(WORKER,{type:'module'});worker.current=w;
   w.onmessage=({data})=>{
    if(data.type==='status')setStatus(data.message);
    if(data.type==='loading')setProgress(data.progress??0);
    if(data.type==='start'){setPromptTokens(data.promptTokens);setStatus('Decoding actual weights');}
    if(data.type==='benchmark-result'){setBrowserBench(data);setStatus(data.passed?'Browser benchmark complete':'Browser benchmark failed');}
    if(data.type==='token'){
      if(!first.current){first.current=true;setTtft(performance.now()-started.current);}
      setOutput(s=>s+data.text);setGenerated(n=>n+1);setElapsed(performance.now()-started.current);
    }
    if(data.type==='done'){setBusy(false);setStatus('Complete');}
    if(data.type==='error'){setBusy(false);setStatus('Error: '+data.message);}
   };return()=>w.terminate();},[]);
 async function run(){setBusy(true);setOutput('');setGenerated(0);setTtft(null);setElapsed(0);setProgress(0);first.current=false;started.current=performance.now();setStatus('Preparing…');
   if(model.backend==='wasm')worker.current?.postMessage({repo:model.repo,prompt,maxTokens:96});
   else try{
     const res=await fetch('/api/infer',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+key},body:JSON.stringify({prompt,model:model.repo,max_tokens:96})});
     const result=await res.json();if(!res.ok)throw Error(result.detail||'Gateway error');
     const text=result.choices?.[0]?.text??'';setOutput(text);setGenerated(result.usage?.completion_tokens??0);
     setPromptTokens(result.usage?.prompt_tokens??0);setTtft(null);setElapsed(performance.now()-started.current);setStatus('Complete · actual GPU response, TTFT not measured');
   }catch(e){setStatus('Error: '+String(e));}finally{setBusy(false);}
 }
 function benchmarkBrowser(){
   if(model.backend!=='wasm'||busy)return;
   setBrowserBench(null);setBusy(true);setStatus('Measuring real browser inference…');
   worker.current?.postMessage({repo:model.repo,prompt:'Explain how a CPU executes instructions.',maxTokens:48,benchmark:true});
 }
 const tokens=prompt.trim()?prompt.trim().split(/\s+/):[];const blocks=blockTable(tokens,previous);
 const hit=blocks.filter(b=>b.cached).length;
 useEffect(()=>{if(model.backend!=='gpu'||!key)return;const update=async()=>{try{const r=await fetch('/api/cache/status',{headers:{Authorization:'Bearer '+key}});if(r.ok)setCache(await r.json());}catch{}};update();const timer=setInterval(update,5000);return()=>clearInterval(timer);},[model,key]);
 return <div className="shell"><header><div className="brand">◈ <b>INFERENCE LAB</b><span>/ CodesbyFebin</span></div><div className="live"><i/> LOCAL + PRIVATE GPU</div></header>
 <section className="intro"><p className="eyebrow">DUAL-RUNTIME OBSERVABILITY CONSOLE / 01</p><h1>See every token.<br/><em>Understand the cache.</em></h1><p>Real model inference, token streaming, and explicitly labeled cache estimates versus GPU telemetry.</p></section>
 <div className="layout"><main><div className="panel"><div className="paneltitle">01 / Inference workspace <span>{model.backend==='wasm'?'BROWSER · WebGPU':'SERVER · vLLM'}</span></div>
 <label>MODEL CHECKPOINT</label><select value={model.name} onChange={e=>setModel(models.find(m=>m.name===e.target.value)!)}>{models.map(m=><option key={m.name}>{m.name}</option>)}</select>
 <div className="spec"><span>{model.sizeMB.toLocaleString()} MB weights</span><span>{model.kvHeads} KV heads</span><span>{model.contextWindow.toLocaleString()} context</span><span>{model.format}</span></div>
 {model.backend==='gpu'&&<><label>GATEWAY BEARER TOKEN (session only)</label><input type="password" value={key} onChange={e=>setKey(e.target.value)} placeholder="Enter gateway token"/></>}
 <label>PROMPT <small>{model.backend==='wasm'?'384 token maximum · validated with model tokenizer':'GPU prompt'}</small></label><textarea value={prompt} onChange={e=>setPrompt(e.target.value)} rows={5}/>
 <div className="actions"><button disabled={busy||!prompt.trim()||model.backend==='gpu'&&!key} onClick={run}>{busy?'RUNNING…':'▶ RUN INFERENCE'}</button><button className="secondary" disabled={busy} onClick={()=>setPrevious(tokens)}>SAVE PREFIX</button><button className="secondary" disabled={busy||model.backend!=='wasm'} onClick={benchmarkBrowser}>BENCHMARK</button></div>
 <p className="status">{status}{busy&&progress>0?` · ${progress.toFixed(0)}%`:''}</p></div>
 <div className="panel response"><div className="paneltitle">02 / Token stream <span>MODEL OUTPUT · NOT MOCKED</span></div><div className="generated">{output||<span className="muted">Generated tokens will appear here…</span>}{busy&&<span className="cursor">▌</span>}</div></div>
 <div className="panel"><div className="paneltitle">03 / Prefix block explorer <span>LOGICAL SIMULATION · 16 TOKENS / BLOCK</span></div><p className="muted">Select “Save prefix”, then edit or extend the prompt. Green blocks indicate an identical full 16-token segment. This explorer uses whitespace units, not tokenizer IDs.</p><div className="blocks">{blocks.map(b=><div className={'block '+(b.cached?'hit':'')} key={b.index}><strong>#{String(b.index).padStart(2,'0')}</strong><span>{b.tokens.length}/16</span><small>{b.cached?'PREFIX HIT':'COMPUTE'}</small></div>)}</div><p className="muted">{hit} matching full blocks · {blocks.length-hit} recompute blocks</p></div></main>
 <aside><div className="panel"><div className="paneltitle">LIVE METRICS <span>SESSION</span></div><div className="stats"><div><label>TIME TO FIRST TOKEN</label><strong>{ttft===null?'—':`${Math.round(ttft)} ms`}</strong></div><div><label>OUTPUT RATE</label><strong>{generated&&elapsed?`${(generated/(elapsed/1000)).toFixed(1)}`:'—'} <small>chunks/s*</small></strong></div><div><label>GENERATED CHUNKS</label><strong>{generated}</strong></div><div><label>PROMPT TOKENS</label><strong>{promptTokens||'—'}</strong></div></div><p className="muted tiny">*Browser streamer chunks are not guaranteed to equal model tokens. GPU totals are backend-reported.</p></div>
 <div className="panel"><div className="paneltitle">KV CACHE <span>{model.backend==='gpu'?'REAL AGGREGATE':'ESTIMATED · LOGICAL'}</span></div>{model.backend==='gpu'?<><h2>{cache?.utilization==null?'—':(cache.utilization*100).toFixed(1)+'%'}</h2><p className="muted">vLLM reported KV pool utilization. Physical block ownership not exposed.</p><p>Prefix hit rate: {cache?.prefixHitRate==null?'unavailable':(cache.prefixHitRate*100).toFixed(1)+'%'}</p></>:<><div className="cachegrid">{Array.from({length:64},(_,i)=><span key={i} className={i<Math.ceil((promptTokens+generated)/16)?'used':''}/>)}</div><p className="muted">Logical 16-token cells for this session, display capacity 64 blocks. Not actual ONNX Runtime allocation.</p></>}</div>
 <div className="panel"><div className="paneltitle">BROWSER BENCHMARK <span>MEASURED · LOCAL ONLY</span></div>{browserBench?<><h2>{browserBench.passed?'PASS':'FAIL'}</h2><p>TTFT: {browserBench.ttftMs?.toFixed(0)??'—'} ms</p><p>Throughput: {browserBench.throughputTokPerSec.toFixed(1)} tokens/s</p><p>{browserBench.completionTokens} output tokens</p></>:<p className="muted">Run the browser benchmark to load the selected model and measure actual generation. These client-side results are not automatically trusted by the gateway.</p>}</div>
 <div className="panel"><div className="paneltitle">EXECUTION POLICY</div><ul><li>Browser: WebGPU q4f16</li><li>Weights cached by runtime</li><li>No synthetic completions</li><li>GPU: private authenticated gateway</li></ul></div></aside></div><footer>INFERENCE LAB / CodesbyFebin · Experimental telemetry, explicitly sourced</footer></div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
