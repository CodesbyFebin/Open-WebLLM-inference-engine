import {pipeline, TextStreamer, env} from '@huggingface/transformers';
env.useBrowserCache = true;
let pipe: any;
let loadedRepo = '';
self.onmessage = async (event:MessageEvent) => {
  const {repo,prompt,maxTokens,benchmark=false}=event.data;
  try {
    if (!pipe || loadedRepo!==repo) {
      self.postMessage({type:'status',message:'Downloading / loading real q4f16 weights…'});
      pipe=await pipeline('text-generation',repo,{device:'webgpu',dtype:'q4f16',progress_callback:(p:any)=>{
        if (p.status==='progress') self.postMessage({type:'loading',progress:p.progress});
      }});
      loadedRepo=repo;
    }
    const tokenizer=pipe.tokenizer;
    const input=await tokenizer(prompt);
    const promptTokens=Number(input.input_ids.dims.at(-1));
    if(promptTokens>384) throw new Error(`Prompt contains ${promptTokens} tokens; maximum is 384.`);
    self.postMessage({type:'start',promptTokens});
    const started=performance.now();
    let firstTokenAt:number|null=null;
    let generatedText='';
    const streamer=new TextStreamer(tokenizer,{skip_prompt:true,skip_special_tokens:true,
      callback_function:(piece:string)=>{
        if(firstTokenAt===null)firstTokenAt=performance.now();
        generatedText+=piece;
        if(!benchmark)self.postMessage({type:'token',text:piece});
      }});
    await pipe(prompt,{max_new_tokens:maxTokens,do_sample:true,temperature:0.7,streamer});
    if(benchmark){
      const generatedIds=await tokenizer(generatedText,{add_special_tokens:false});
      const completionTokens=Number(generatedIds.input_ids.dims.at(-1));
      const elapsedMs=performance.now()-started;
      self.postMessage({type:'benchmark-result',source:'browser-model-weights',model:repo,
        promptTokens,completionTokens,elapsedMs,
        ttftMs:firstTokenAt===null?null:firstTokenAt-started,
        throughputTokPerSec:elapsedMs>0?completionTokens*1000/elapsedMs:0,
        passed:generatedText.trim().length>0&&completionTokens>0});
    }
    self.postMessage({type:'done'});
  } catch(e){self.postMessage({type:'error',message:e instanceof Error?e.message:String(e)});}
};
