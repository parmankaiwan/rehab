"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, RefreshCw } from "lucide-react";
import type { PatientSession } from "@/types/patientSession";
import { PatientStepper } from "./PatientStepper";

const api = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
function duration(value:number) { const seconds=Math.max(0,Math.floor(value)); return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,"0")}`; }

export function PatientSessionSummary() {
  const id=useSearchParams().get("session");
  const [session,setSession]=useState<PatientSession|null>(null);
  const [error,setError]=useState("");
  const load=useCallback(async()=>{
    if(!id){setError("Session summary is unavailable.");return;}
    try{const response=await fetch(`${api}/api/patient/sessions/${id}/summary`,{cache:"no-store"});if(!response.ok)throw new Error("Session summary could not be loaded.");setSession(await response.json());setError("");}
    catch(reason){setError(reason instanceof Error?reason.message:"Session summary could not be loaded.");}
  },[id]);
  useEffect(()=>{void load();},[load]);
  if(error)return <div className="patient-flow"><main className="summary-page"><h1>{error}</h1><button className="summary-done" onClick={()=>void load()}><RefreshCw/>Retry</button><Link className="summary-done" href="/">Return home</Link></main></div>;
  if(!session)return <main><div className="loading-skeleton"><i/><i/><i/></div></main>;
  return <div className="patient-flow"><header className="patient-simple-header"><Link href="/">FLEXMAP</Link></header><main className="summary-page"><PatientStepper current={4}/><CheckCircle2/><span className="eyebrow">Session complete</span><h1>Well done.</h1><p>Your {session.exercise_id.replaceAll("_"," ")} session is complete.</p><div className="summary-stats">{session.completed_repetitions!=null&&<div><strong>{session.target_repetitions!=null?`${session.completed_repetitions} / ${session.target_repetitions}`:session.completed_repetitions}</strong><span>Repetitions</span></div>}<div><strong>{duration(session.active_duration)}</strong><span>Active time</span></div><div><strong>{duration(session.elapsed_duration)}</strong><span>Total time</span></div><div><strong>{session.tracking_state.toLowerCase().replaceAll("_"," ")}</strong><span>Tracking</span></div></div><p className="patient-safety">FlexMap does not provide a diagnosis. Discuss your rehabilitation plan with a qualified professional.</p><Link className="summary-done" href="/">Done</Link></main></div>;
}
