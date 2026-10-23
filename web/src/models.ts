export type Checkpoint = {name:string; repo:string; sizeMB:number; kvHeads:number; contextWindow:number; backend:'wasm'|'gpu'; format:'q4f16'|'bf16'};
export const models:Checkpoint[] = [
  {name:'SmolLM2-135M-Instruct',repo:'onnx-community/SmolLM2-135M-Instruct-ONNX',sizeMB:118,kvHeads:3,contextWindow:8192,backend:'wasm',format:'q4f16'},
  {name:'SmolLM2-360M-Instruct',repo:'onnx-community/SmolLM2-360M-Instruct-ONNX',sizeMB:273,kvHeads:5,contextWindow:8192,backend:'wasm',format:'q4f16'},
  {name:'SmolLM-135M-Instruct',repo:'onnx-community/SmolLM-135M-Instruct-ONNX',sizeMB:117,kvHeads:3,contextWindow:2048,backend:'wasm',format:'q4f16'},
  {name:'Qwen2.5-0.5B-Instruct',repo:'onnx-community/Qwen2.5-0.5B-Instruct',sizeMB:483,kvHeads:2,contextWindow:32768,backend:'wasm',format:'q4f16'},
  {name:'Qwen2.5-7B-Instruct · GPU',repo:'Qwen/Qwen2.5-7B-Instruct',sizeMB:15000,kvHeads:4,contextWindow:32768,backend:'gpu',format:'bf16'}
];
export const BLOCK_SIZE=16;
export function blockTable(tokens:string[], previous:string[]=[]){
  const count=Math.ceil(tokens.length/BLOCK_SIZE);
  return Array.from({length:count},(_,i)=>{
    const segment=tokens.slice(i*BLOCK_SIZE,(i+1)*BLOCK_SIZE);
    const old=previous.slice(i*BLOCK_SIZE,(i+1)*BLOCK_SIZE);
    return {index:i,tokens:segment,cached:segment.length===BLOCK_SIZE && old.length===BLOCK_SIZE && segment.every((t,k)=>t===old[k])};
  });
}
