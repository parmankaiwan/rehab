import { MasterHeader } from "./MasterHeader";

export function MasterShell() {
  return <div className="master-shell"><MasterHeader/><main className="master-workspace"><span className="eyebrow">Private workspace</span><h1>Master Dashboard</h1><div className="master-empty"><span>Master workspace ready.</span></div></main></div>;
}
