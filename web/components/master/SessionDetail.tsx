"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { ResearchSession } from "@/types/session";

export function SessionDetail({id}:{id:string}) {
  const [session,setSession]=useState<ResearchSession|null>();
  const [error,setError]=useState("");
  const [notes,setNotes]=useState("");
  const [saved,setSaved]=useState(false);
  const load=useCallback(async()=>{setError("");const response=await fetch(`/api/master/data/sessions/${id}`);if(response.ok){const value=await response.json();setSession(value);setNotes(value.notes||"");}else setError(response.status===404?"Session not found.":"Could not load this session.");},[id]);
  useEffect(()=>{void load();},[load]);
  async function saveNotes(){const response=await fetch(`/api/master/data/sessions/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({notes})});if(response.ok){setSession(await response.json());setSaved(true);setTimeout(()=>setSaved(false),2500);}else setError("Could not save session notes.");}
  if(error)return <div className="master-error-state"><h2>{error}</h2><button onClick={()=>void load()}><RefreshCw/>Retry</button></div>;
  if(!session)return <div className="loading-skeleton" aria-label="Loading session"><i/><i/><i/></div>;
  const slug=session.rehab_type.toLowerCase();
  const query=new URLSearchParams({session_id:session.session_id,subject_id:session.subject_id,rehab_type:session.rehab_type,affected_side:session.affected_side,protocol_id:session.protocol_id||""}).toString();
  return <section><nav className="breadcrumbs"><Link href="/master">Master</Link><span>›</span><Link href="/master/sessions">Sessions</Link><span>›</span><strong>{session.session_id}</strong></nav><span className="eyebrow">Research session</span><h1>{session.session_id}</h1><div className="session-overview"><div><span>Subject</span><strong>{session.subject_id}</strong></div><div><span>Rehab</span><strong>{session.rehab_type.replaceAll("_"," ")}</strong></div><div><span>Affected side</span><strong>{session.affected_side}</strong></div><div><span>Status</span><strong className={`status-token status-${session.status.toLowerCase()}`}>{session.status}</strong></div></div><div className="modality-pair"><article className="master-card modality-card cv"><small>Movement / Kinematics</small><h2>Computer Vision</h2><strong>{session.cv_recording_ids.length} recordings</strong><div><Link href={`/master/cv-data/${slug}?${query}`}>Collect CV</Link><Link className="secondary-link" href={`/master/dataset/rehab/${slug}?modality=cv&session_id=${session.session_id}`}>View recordings</Link></div></article><article className="master-card modality-card emg"><small>Muscle Electrical Activity</small><h2>EMG</h2><strong>{session.emg_recording_ids.length} recordings</strong><div><Link href={`/master/emg/${slug}?${query}`}>Collect EMG</Link><Link className="secondary-link" href={`/master/dataset/rehab/${slug}?modality=emg&session_id=${session.session_id}`}>View recordings</Link></div></article></div><section className="master-card activity-timeline"><div className="master-card-head"><div><h2>Activity timeline</h2><p>Chronological activity only · Sensor synchronization is <strong>not configured</strong>.</p></div></div>{session.activity.length?session.activity.map((event,index)=><div className="timeline-event" key={`${event.type}-${index}`}><time>{new Date(event.timestamp).toLocaleString()}</time><i/><span>{event.label}</span></div>):<p>No session activity yet.</p>}</section><section className="master-card session-notes"><h2>Session notes</h2><p>Do not include unnecessary identifying information.</p><textarea value={notes} onChange={event=>setNotes(event.target.value)} maxLength={2000}/><button className="primary" onClick={()=>void saveNotes()}>Save notes</button>{saved&&<span role="status">Notes saved.</span>}</section></section>;
}
