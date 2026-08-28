import { LockKeyhole, RotateCcw, Settings } from "lucide-react";
import Link from "next/link";
import { ConnectionState } from "@/types/posture";

function connectionCopy(connection: ConnectionState, cvLive: boolean, mock: boolean) {
  if (mock) return { label: "MOCK DATA", tone: "mock" };
  if (connection === "CONNECTED" && cvLive) return { label: "CV Live", tone: "connected" };
  if (connection === "CONNECTED") return { label: "Waiting for CV", tone: "waiting" };
  if (connection === "CONNECTING") return { label: "Reconnecting", tone: "connecting" };
  return { label: "Backend offline", tone: "disconnected" };
}

export function PatientHeader({ connection, cvLive, mock, onSettings, onReset }: { connection: ConnectionState; cvLive: boolean; mock: boolean; onSettings(): void; onReset(): void }) {
  const status = connectionCopy(connection, cvLive, mock);
  return <header className="header"><div className="brand"><span className="brand-mark" aria-hidden="true"><i/><i/><i/></span><div><strong>FlexMap</strong><span>Posture Rehabilitation System</span></div></div><div className="header-actions"><Link href="/master" className="master-nav-link" aria-label="Open Master access"><LockKeyhole size={15}/><span>Master</span></Link><span className={`connection connection--${status.tone}`}><i aria-hidden="true"/>{status.label}</span><button className="icon-button reset-button" onClick={onReset} aria-label="Reset posture reference"><RotateCcw size={18}/><span>Reset</span></button><button className="icon-button" onClick={onSettings} aria-label="Open settings"><Settings size={20}/></button></div></header>;
}
