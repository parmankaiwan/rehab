"use client";

import { memo, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";
import { patientComponentLabels } from "@/lib/patientCopy";
import { BodyRegion, COMPONENT_REGION } from "@/lib/bodyRegionMap";
import { PostureComponent, PostureSnapshot, PostureState } from "@/types/posture";
import { StateIcon } from "./icons";

export const CORE: [string, string][] = [["TRUNK_VERTICAL", "Trunk Upright"], ["TRUNK_CENTERED", "Trunk Center"], ["FRONT_FACING", "Front Facing"], ["BODY_TRACKING_COMPLETE", "Body Tracking"]];
export const ALIGNMENT: [string, string][] = [["HEAD_LEVEL", "Head Level"], ["HEAD_CENTERED", "Head Center"], ["SHOULDER_LEVEL", "Shoulder Level"], ["SHOULDER_SYMMETRY", "Shoulder Symmetry"], ["HIP_LEVEL", "Hip Level"], ["HIP_SYMMETRY", "Hip Symmetry"]];

function component(snapshot: PostureSnapshot | null, key: string): PostureComponent {
  if (key === "BODY_TRACKING_COMPLETE" && !snapshot?.components[key]) {
    const states = ["LEFT_ARM_VISIBLE", "RIGHT_ARM_VISIBLE", "LEFT_HIP_VISIBLE", "RIGHT_HIP_VISIBLE"].map((name) => snapshot?.components[name]?.state);
    return { state: states.includes("GREY") ? "GREY" : states.includes("RED") ? "RED" : states.includes("ORANGE") ? "ORANGE" : "GREEN" };
  }
  return snapshot?.components[key] ?? { state: "GREY" };
}

const ComponentItem = memo(function ComponentItem({ componentKey, name, item, research, measurements, selected, onHover, onSelect }: { componentKey: string; name: string; item: PostureComponent; research: boolean; measurements: boolean; selected: boolean; onHover?: (region: BodyRegion | null) => void; onSelect?: (region: BodyRegion | null) => void }) {
  const value = item.value == null ? null : `${item.value.toFixed(item.units === "deg" ? 1 : 2)}${item.units ? ` ${item.units}` : ""}`;
  return <li data-state={item.state} className={selected ? "selected" : ""} tabIndex={0} aria-label={`${name}: ${patientComponentLabels[item.state]}`} onMouseEnter={() => onHover?.(COMPONENT_REGION[componentKey] ?? null)} onMouseLeave={() => onHover?.(null)} onClick={() => onSelect?.(COMPONENT_REGION[componentKey] ?? null)} onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && onSelect?.(COMPONENT_REGION[componentKey] ?? null)}><span className={`component-dot state-${item.state.toLowerCase()}`}><StateIcon state={item.state} size={15}/></span><span className="component-copy"><strong>{name}</strong><small>{research ? <><span>{item.state}</span>{measurements && value && <span className="measurement-inline"> · {value}</span>}</> : measurements && value ? value : patientComponentLabels[item.state]}</small></span>{research && item.confidence != null && <span className="confidence">{Math.round(item.confidence * 100)}%</span>}</li>;
});

function summary(items: PostureComponent[]): string {
  const counts = items.reduce<Record<PostureState, number>>((value, item) => ({ ...value, [item.state]: value[item.state] + 1 }), { GREEN: 0, ORANGE: 0, RED: 0, GREY: 0 });
  const parts = [[counts.GREEN, "ready"], [counts.ORANGE, "close"], [counts.RED, "adjust"], [counts.GREY, "not tracked"]].filter(([count]) => count);
  return parts.map(([count, label]) => `${count} ${label}`).join(" · ");
}

export function CompactPostureComponents({ snapshot, research, measurements, activeRegion, onHover, onSelect }: { snapshot: PostureSnapshot | null; research: boolean; measurements: boolean; activeRegion?: BodyRegion | null; onHover?: (region: BodyRegion | null) => void; onSelect?: (region: BodyRegion | null) => void }) {
  const [expanded, setExpanded] = useState(false);
  const core = useMemo(() => CORE.map(([key]) => component(snapshot, key)), [snapshot]);
  const alignment = useMemo(() => ALIGNMENT.map(([key]) => component(snapshot, key)), [snapshot]);
  const section = (title: string, items: [string, string][], values: PostureComponent[]) => <div className="compact-group"><div className="compact-group-heading"><h3>{title}</h3><span>{summary(values)}</span></div><ul>{items.map(([key, name], index) => <ComponentItem key={key} componentKey={key} name={name} item={values[index]} research={research} measurements={measurements} selected={COMPONENT_REGION[key] === activeRegion} onHover={onHover} onSelect={onSelect}/>)}</ul></div>;
  return <section className={`compact-components ${expanded || research ? "expanded" : ""}`}><div className="compact-components-head"><div><span className="eyebrow">Posture summary</span><h2>Position check</h2></div><button className="details-button" aria-expanded={expanded || research} onClick={() => setExpanded(!expanded)}>{expanded ? "Hide details" : "View details"}<ChevronDown size={16}/></button></div><div className="compact-grid">{section("Core", CORE, core)}{section("Alignment", ALIGNMENT, alignment)}</div></section>;
}
