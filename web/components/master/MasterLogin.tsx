"use client";
import { FormEvent, useState } from "react";
import { Eye, EyeOff, LockKeyhole } from "lucide-react";
import { useRouter } from "next/navigation";

export function MasterLogin() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError("");
    try {
      const response = await fetch("/api/master/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }) });
      const result = await response.json() as { success: boolean; error?: string };
      if (!response.ok || !result.success) { setError(response.status === 429 ? result.error || "Too many attempts. Try again later." : "Incorrect password."); return; }
      setPassword(""); router.refresh();
    } catch { setError("Master access is temporarily unavailable."); }
    finally { setLoading(false); }
  }
  return <main className="master-login-page"><section className="master-login-card" aria-labelledby="master-login-title"><div className="master-login-mark"><LockKeyhole aria-hidden="true"/></div><span className="eyebrow">FlexMap Rehab</span><h1 id="master-login-title">Master Access</h1><p>Authorized access only.</p><form onSubmit={submit}><label htmlFor="master-password">Password</label><div className="master-password-field"><input id="master-password" type={visible ? "text" : "password"} value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" autoFocus required disabled={loading}/><button type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? "Hide password" : "Show password"}>{visible ? <EyeOff/> : <Eye/>}</button></div>{error && <p className="master-error" role="alert">{error}</p>}<button className="master-unlock" type="submit" disabled={loading || !password}>{loading ? "Unlocking..." : "Unlock Master Dashboard"}</button></form></section></main>;
}
