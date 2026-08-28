"use client";
import { BodyRegion, regionState } from "@/lib/bodyRegionMap";
import { PostureSnapshot } from "@/types/posture";

const regions: { key: BodyRegion; label: string }[] = [{ key: "HEAD", label: "Head" }, { key: "SHOULDERS", label: "Shoulders" }, { key: "TRUNK", label: "Trunk" }, { key: "HIPS", label: "Hips" }, { key: "LEFT_ARM", label: "Left arm" }, { key: "RIGHT_ARM", label: "Right arm" }];

export function LiveBodyMap({ snapshot, active, onSelect }: { snapshot: PostureSnapshot | null; active: BodyRegion | null; onSelect: (region: BodyRegion | null) => void }) {
  const activate = (region: BodyRegion) => onSelect(region);
  return <div className="live-body-map"><span className="eyebrow">Live body map</span><svg viewBox="0 0 160 220" aria-label="Interactive posture body map">
    <g className={`map-region state-${regionState(snapshot, "HEAD").toLowerCase()} ${active === "HEAD" ? "active" : ""}`} role="button" tabIndex={0} aria-label="Head region" onClick={() => activate("HEAD")} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && activate("HEAD")}><circle cx="80" cy="30" r="20"/></g>
    <g className={`map-region state-${regionState(snapshot, "SHOULDERS").toLowerCase()} ${active === "SHOULDERS" ? "active" : ""}`} role="button" tabIndex={0} aria-label="Shoulders region" onClick={() => activate("SHOULDERS")} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && activate("SHOULDERS")}><path d="M45 65 Q80 52 115 65"/></g>
    <g className={`map-region state-${regionState(snapshot, "TRUNK").toLowerCase()} ${active === "TRUNK" ? "active" : ""}`} role="button" tabIndex={0} aria-label="Trunk region" onClick={() => activate("TRUNK")} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && activate("TRUNK")}><path d="M52 68 L108 68 L100 145 L60 145 Z"/></g>
    <g className={`map-region state-${regionState(snapshot, "HIPS").toLowerCase()} ${active === "HIPS" ? "active" : ""}`} role="button" tabIndex={0} aria-label="Hips region" onClick={() => activate("HIPS")} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && activate("HIPS")}><path d="M58 145 Q80 158 102 145"/></g>
    <g className={`map-region state-${regionState(snapshot, "LEFT_ARM").toLowerCase()} ${active === "LEFT_ARM" ? "active" : ""}`} role="button" tabIndex={0} aria-label="Left arm region" onClick={() => activate("LEFT_ARM")} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && activate("LEFT_ARM")}><path d="M48 70 L28 120 L20 172"/></g>
    <g className={`map-region state-${regionState(snapshot, "RIGHT_ARM").toLowerCase()} ${active === "RIGHT_ARM" ? "active" : ""}`} role="button" tabIndex={0} aria-label="Right arm region" onClick={() => activate("RIGHT_ARM")} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && activate("RIGHT_ARM")}><path d="M112 70 L132 120 L140 172"/></g>
  </svg><div className="map-labels">{regions.map(({ key, label }) => <button key={key} className={active === key ? "active" : ""} onClick={() => activate(key)}>{label}</button>)}</div></div>;
}
