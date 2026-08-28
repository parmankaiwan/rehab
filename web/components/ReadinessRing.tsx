export function ReadinessRing({ progress, ready }: { progress: number; ready: boolean }) {
  const value = ready ? 100 : Math.round(Math.max(0, Math.min(1, progress)) * 100);
  return <div className={`readiness-ring ${ready ? "complete" : ""}`} style={{ "--ready-progress": `${value * 3.6}deg` } as React.CSSProperties} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} aria-label="Ready confirmation progress">
    <div><strong>{ready ? "✓" : `${value}%`}</strong><span>READY</span></div>
  </div>;
}
