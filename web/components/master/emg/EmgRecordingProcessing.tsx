"use client";

import { useCallback, useEffect, useState } from "react";
import type { EmgChannel, EmgProcessingConfig, EmgProcessingStatus, EmgSample, SignalRepresentation } from "@/types/emg";
import { EmgChart } from "./EmgChart";

const api="/api/master/data/emg";
type Run={processing_run_id:string;created_at_utc:string;source_raw_sha256:string;processing_config_hash:string;processing_pipeline_version:string;preferred_for_review:boolean;processing_config:EmgProcessingConfig};

export function EmgRecordingProcessing({id,channels}:{id:string;channels:EmgChannel[]}) {
  const [runs,setRuns]=useState<Run[]>([]);
  const [config,setConfig]=useState<EmgProcessingConfig|null>(null);
  const [selected,setSelected]=useState<Run|null>(null);
  const [samples,setSamples]=useState<EmgSample[]>([]);
  const [tab,setTab]=useState<"RAW"|"PROCESSED"|"QUALITY">("RAW");
  const [error,setError]=useState("");

  const load=useCallback(async()=>{
    const [runsResponse,configResponse]=await Promise.all([fetch(`${api}/recordings/${id}/processing-runs`),fetch(`${api}/processing/config`)]);
    if(runsResponse.ok){const list:Run[]=await runsResponse.json();setRuns(list);setSelected(current=>current||list[0]||null);}
    if(configResponse.ok){const value:EmgProcessingStatus=await configResponse.json();setConfig(value.config);}
  },[id]);

  useEffect(()=>{void load();},[load]);
  useEffect(()=>{
    if(!selected)return;
    let active=true;
    fetch(`${api}/recordings/${id}/processing-runs/${selected.processing_run_id}/waveform`).then(async response=>{
      if(!response.ok||!active)return;
      const body:{samples:Record<string,string>[]}=await response.json();
      if(!active)return;
      setSamples(body.samples.map(row=>{const processed:EmgSample["processed"]={};for(const channel of channels){processed[channel.internal_id]={};for(const representation of ["filtered","rectified","rms","envelope"] as SignalRepresentation[]){const value=row[`${channel.internal_id}_${representation}`];if(value!==""&&value!=null)processed[channel.internal_id]![representation]=Number(value);}}return{sequence_id:Number(row.sequence_id),host_timestamp_ns:Number(row.host_timestamp_ns),t_ms:0,channels:{},processed,valid:true};}));
    });
    return()=>{active=false};
  },[id,selected,channels]);

  async function reprocess(){if(!config)return;setError("");const before=runs.map(item=>item.source_raw_sha256);const response=await fetch(`${api}/recordings/${id}/reprocess`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...config,enabled:true})});const value=await response.json();if(!response.ok){setError(value.detail||"Reprocessing failed");return;}await load();if(before.length&&before.some(hash=>hash!==value.source_raw_sha256))setError("RAW HASH MISMATCH");}

  return <article className="master-card"><div className="master-card-head"><strong>Recording processing</strong><span>{runs.length?`${runs.length} RUN${runs.length===1?"":"S"}`:"RAW RECORDING"}</span></div><div className="review-actions horizontal">{(["RAW","PROCESSED","QUALITY"] as const).map(value=><button className={tab===value?"primary":""} onClick={()=>setTab(value)} key={value}>{value}</button>)}</div>{tab==="RAW"&&<p>Canonical raw recording. Processing: {runs.length?"available in separate immutable runs":"NOT YET GENERATED"}.</p>}{tab==="PROCESSED"&&<>{runs.length?<><label>Processing run<select value={selected?.processing_run_id||""} onChange={event=>setSelected(runs.find(item=>item.processing_run_id===event.target.value)||null)}>{runs.map(run=><option key={run.processing_run_id}>{run.processing_run_id}</option>)}</select></label><EmgChart samples={samples} channels={channels} paused={false} initialSignal="filtered"/><pre>{JSON.stringify(selected,null,2)}</pre></>:<p>Legacy/raw-only recording. Select PROCESS RECORDING to create a derived run.</p>}</>}{tab==="QUALITY"&&<pre>{selected?JSON.stringify({source_raw_sha256:selected.source_raw_sha256,processing_config_hash:selected.processing_config_hash,pipeline:selected.processing_pipeline_version},null,2):"Signal quality report not yet generated."}</pre>}{error&&<p className="master-alert">{error}</p>}<button className="primary" disabled={!config} onClick={()=>void reprocess()}>PROCESS RECORDING</button><p>Each run uses a new PROC ID; older runs and raw data remain unchanged.</p></article>;
}
