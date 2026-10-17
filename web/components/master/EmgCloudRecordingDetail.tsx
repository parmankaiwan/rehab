"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Check, RotateCcw, Save, Trash2, X } from "lucide-react";

type Artifact = { artifact_id:string; artifact_role:string; content_type:string; byte_size:number };
type Detail = {
  recording_id:string; dataset_id:string; research_label:string; subject_code:string; session_id?:string;
  duration_seconds:number; sample_rate_hz?:number; signal_units:string; channel_count:number; review_status:string;
  review_notes?:string; training_eligible:boolean; excluded:boolean; exclusion_reason?:string; trashed_at?:string|null;
  quality_report?:unknown; hardware_snapshot?:unknown; artifacts:Artifact[];
};
type Waveform = { raw_units:string; sample_rate_hz?:number; duration_seconds?:number; samples:Array<Record<string,string>> };
type Dataset = { dataset_id:string; labels?:Array<{name:string; archived?:boolean}> };
type ReviewDraft = { research_label:string; review_notes:string; training_eligible:boolean; excluded:boolean; exclusion_reason:string };

export function EmgCloudRecordingDetail({ id }:{ id:string }) {
  const [detail,setDetail]=useState<Detail|null>(null);
  const [waveform,setWaveform]=useState<Waveform|null>(null);
  const [labels,setLabels]=useState<string[]>([]);
  const [draft,setDraft]=useState<ReviewDraft|null>(null);
  const [channel,setChannel]=useState("");
  const [zoom,setZoom]=useState(100);
  const [pan,setPan]=useState(0);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [busy,setBusy]=useState(false);

  useEffect(()=>{
    let active=true;
    Promise.all([
      fetch(`/api/master/data/emg/cloud-recordings/${id}`,{cache:"no-store"}),
      fetch(`/api/master/data/emg/cloud-recordings/${id}/waveform?max_points=2500`,{cache:"no-store"}),
      fetch("/api/master/data/emg/cloud-datasets",{cache:"no-store"}),
    ]).then(async([detailResponse,waveformResponse,datasetsResponse])=>{
      const detailBody=await detailResponse.json();
      const waveformBody=await waveformResponse.json();
      const datasetsBody=datasetsResponse.ok?await datasetsResponse.json():[];
      if(!detailResponse.ok||!waveformResponse.ok)throw new Error(detailBody.detail||waveformBody.detail||"Unable to load EMG recording");
      if(!active)return;
      const recording=detailBody as Detail;
      setDetail(recording);
      setWaveform(waveformBody);
      setDraft({research_label:recording.research_label,review_notes:recording.review_notes||"",training_eligible:Boolean(recording.training_eligible),excluded:Boolean(recording.excluded),exclusion_reason:recording.exclusion_reason||""});
      const dataset=(datasetsBody as Dataset[]).find(item=>item.dataset_id===recording.dataset_id);
      setLabels((dataset?.labels||[]).filter(item=>!item.archived).map(item=>item.name));
    }).catch(reason=>active&&setError(reason instanceof Error?reason.message:"Unable to load EMG recording"));
    return()=>{active=false};
  },[id]);

  const channels=useMemo(()=>waveform?.samples.length?Object.keys(waveform.samples[0]).filter(key=>!key.toLowerCase().includes("time")&&!key.toLowerCase().includes("sequence")):[],[waveform]);
  useEffect(()=>{if(!channel&&channels.length)setChannel(channels[0])},[channel,channels]);
  const visibleSamples=useMemo(()=>{if(!waveform)return[];const count=Math.max(2,Math.ceil(waveform.samples.length*zoom/100)),available=Math.max(0,waveform.samples.length-count),start=Math.round(available*pan/100);return waveform.samples.slice(start,start+count)},[waveform,zoom,pan]);
  const points=useMemo(()=>{if(!channel)return"";const values=visibleSamples.map(row=>Number(row[channel])).filter(Number.isFinite);if(!values.length)return"";const min=Math.min(...values),max=Math.max(...values),span=Math.max(1,max-min);return values.map((value,index)=>`${(index/Math.max(1,values.length-1))*100},${95-((value-min)/span)*90}`).join(" ")},[visibleSamples,channel]);
  const stats=useMemo(()=>{if(!channel)return null;const values=visibleSamples.map(row=>Number(row[channel])).filter(Number.isFinite);return values.length?{min:Math.min(...values),max:Math.max(...values)}:null},[visibleSamples,channel]);

  async function updateReview(reviewStatus?:"REVIEWED"|"APPROVED"|"REJECTED") {
    if(!draft||!detail)return;
    setBusy(true);setError("");setMessage("");
    try{
      const payload={...draft,review_status:reviewStatus||"REVIEWED",training_eligible:reviewStatus==="APPROVED"?draft.training_eligible:false,excluded:reviewStatus==="REJECTED"?true:draft.excluded,exclusion_reason:reviewStatus==="REJECTED"?draft.exclusion_reason||"REJECTED_BY_REVIEWER":draft.exclusion_reason};
      const response=await fetch(`/api/master/data/emg/cloud-recordings/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
      const body=await response.json();if(!response.ok)throw new Error(body.detail||"Unable to save EMG review");
      setDetail(body);setDraft({research_label:body.research_label,review_notes:body.review_notes||"",training_eligible:Boolean(body.training_eligible),excluded:Boolean(body.excluded),exclusion_reason:body.exclusion_reason||""});setMessage(`Review saved as ${body.review_status}.`);
    }catch(reason){setError(reason instanceof Error?reason.message:"Unable to save EMG review")}finally{setBusy(false)}
  }

  async function setTrashed(trashed:boolean) {
    setBusy(true);setError("");setMessage("");
    try{const response=await fetch(`/api/master/data/emg/cloud-recordings/${id}/${trashed?"trash":"restore"}`,{method:"POST"});const body=await response.json();if(!response.ok)throw new Error(body.detail||`Unable to ${trashed?"trash":"restore"} recording`);setDetail(body);setMessage(trashed?"Recording moved to trash.":"Recording restored.")}
    catch(reason){setError(reason instanceof Error?reason.message:"Unable to update recording")}finally{setBusy(false)}
  }

  if(error&&!detail)return <div className="emgc-alert">{error}</div>;
  if(!detail||!waveform||!draft)return <p>Loading stored EMG waveform…</p>;
  const effectiveLabels=labels.includes(draft.research_label)?labels:[draft.research_label,...labels];

  return <section className="emgc-page">
    <div className="ml-page-head"><div><span className="eyebrow">Durable EMG recording</span><h1>{detail.research_label}</h1><p>{detail.recording_id} · {detail.subject_code} · {detail.session_id||"No session"}</p></div><Link href="/master/dataset/emg">Back to EMG Vault</Link></div>
    {error&&<div className="emgc-alert">{error}</div>}{message&&<div className="master-success">{message}</div>}
    <section className="emgc-record-card"><header><div><span className="eyebrow">Raw signal · {waveform.raw_units}</span><h2>Stored waveform</h2></div><label>Channel<select value={channel} onChange={event=>setChannel(event.target.value)}>{channels.map(name=><option key={name}>{name}</option>)}</select></label></header><div className="emgc-inline"><label>Window<input aria-label="Waveform zoom" type="range" min="5" max="100" value={zoom} onChange={event=>setZoom(Number(event.target.value))}/><span>{zoom}%</span></label><label>Pan<input aria-label="Waveform pan" type="range" min="0" max="100" value={pan} disabled={zoom===100} onChange={event=>setPan(Number(event.target.value))}/></label></div><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`Waveform for ${channel}`} style={{width:"100%",height:360}}><polyline points={points} fill="none" stroke="currentColor" strokeWidth="0.7" vectorEffect="non-scaling-stroke"/></svg><div className="emgc-kpis"><article><span>Minimum<strong>{stats?.min??"—"}</strong></span></article><article><span>Maximum<strong>{stats?.max??"—"}</strong></span></article><article><span>Peak-to-peak<strong>{stats?stats.max-stats.min:"—"}</strong></span></article><article><span>Sample rate<strong>{waveform.sample_rate_hz?`${Math.round(waveform.sample_rate_hz)} Hz`:"—"}</strong></span></article></div></section>
    <section className="emgc-table-card"><div className="master-card-head"><div><span className="eyebrow">Research review</span><h2>Classification and training eligibility</h2></div><strong>{detail.review_status}</strong></div><div className="field-pair"><label>Research label<select value={draft.research_label} onChange={event=>setDraft({...draft,research_label:event.target.value})}>{effectiveLabels.map(name=><option key={name}>{name}</option>)}</select></label><label>Review notes<textarea value={draft.review_notes} onChange={event=>setDraft({...draft,review_notes:event.target.value})}/></label></div><div className="field-pair"><label className="check"><input type="checkbox" checked={draft.training_eligible} disabled={draft.excluded} onChange={event=>setDraft({...draft,training_eligible:event.target.checked})}/> Eligible for training after approval</label><label className="check"><input type="checkbox" checked={draft.excluded} onChange={event=>setDraft({...draft,excluded:event.target.checked,training_eligible:event.target.checked?false:draft.training_eligible})}/> Exclude from research use</label></div><label>Exclusion reason<input value={draft.exclusion_reason} disabled={!draft.excluded} onChange={event=>setDraft({...draft,exclusion_reason:event.target.value})}/></label><div className="review-actions"><button disabled={busy} onClick={()=>void updateReview()}><Save size={16}/> Save review</button><button className="primary" disabled={busy||draft.excluded} onClick={()=>void updateReview("APPROVED")}><Check size={16}/> Approve</button><button className="danger" disabled={busy} onClick={()=>void updateReview("REJECTED")}><X size={16}/> Reject</button>{detail.trashed_at?<button disabled={busy} onClick={()=>void setTrashed(false)}><RotateCcw size={16}/> Restore</button>:<button className="danger" disabled={busy} onClick={()=>void setTrashed(true)}><Trash2 size={16}/> Move to trash</button>}</div><p className="source-note">Review, relabel, eligibility, exclusion, trash, and restore actions are stored in the persistent audit trail.</p></section>
    <section className="emgc-table-card"><h2>Metadata and artifacts</h2><p>Duration: {detail.duration_seconds.toFixed(2)} s · Channels: {detail.channel_count} · Review: {detail.review_status}</p><ul>{detail.artifacts.map(item=><li key={item.artifact_id}><a download href={`/api/master/data/emg/cloud-recordings/${id}/artifacts/${item.artifact_id}`}>{item.artifact_role}</a> ({Math.round(item.byte_size/1024)} KB)</li>)}</ul><details><summary>Technical quality and hardware metadata</summary><pre>{JSON.stringify({quality:detail.quality_report,hardware:detail.hardware_snapshot},null,2)}</pre></details></section>
  </section>;
}
