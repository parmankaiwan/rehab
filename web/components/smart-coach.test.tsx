import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { COMPONENT_REGION, selectCoach } from "@/lib/bodyRegionMap";
import { PostureSnapshot } from "@/types/posture";
import { LiveBodyMap } from "./LiveBodyMap";
import { CameraBodyOverlay } from "./CameraBodyOverlay";

function snapshot(overrides: Partial<PostureSnapshot> = {}): PostureSnapshot {
  return { timestamp: 1, connected: true, tracking_quality: "GOOD", overall_state: "ORANGE", ready: false, ready_progress: 0, feedback: [], components: { BODY_TRACKING_COMPLETE: { state: "GREEN" }, FRONT_FACING: { state: "GREEN" }, TRUNK_VERTICAL: { state: "GREEN" }, TRUNK_CENTERED: { state: "GREEN" }, SHOULDER_LEVEL: { state: "GREEN" }, SHOULDER_SYMMETRY: { state: "GREEN" }, HEAD_LEVEL: { state: "GREEN" }, HEAD_CENTERED: { state: "GREEN" }, HIP_LEVEL: { state: "GREEN" }, HIP_SYMMETRY: { state: "GREEN" } }, ...overrides };
}

describe("Smart Ready Coach", () => {
  it("prioritizes missing tracking over alignment", () => {
    const data = snapshot({ components: { ...snapshot().components, LEFT_ARM_VISIBLE: { state: "GREY" }, SHOULDER_LEVEL: { state: "RED" } } });
    expect(selectCoach(data)).toMatchObject({ stage: "TRACKING", primary: "KEEP LEFT ARM VISIBLE", region: "LEFT_ARM" });
  });
  it("prioritizes trunk over a shoulder warning", () => {
    const data = snapshot({ components: { ...snapshot().components, TRUNK_VERTICAL: { state: "RED" }, SHOULDER_LEVEL: { state: "ORANGE" } } });
    expect(selectCoach(data)).toMatchObject({ stage: "POSITIONING", primary: "SIT UPRIGHT", region: "TRUNK" });
  });
  it("uses backend progress to enter holding and clears corrections when ready", () => {
    expect(selectCoach(snapshot({ ready_progress: .74, ready_stage: "HOLD_STILL" }))).toMatchObject({ stage: "HOLDING", primary: "HOLD POSITION" });
    expect(selectCoach(snapshot({ ready: true, ready_progress: 1, overall_state: "GREEN" }))).toMatchObject({ stage: "READY", primary: "READY", region: null });
  });
  it("maps posture keys to stable body regions", () => {
    expect(COMPONENT_REGION).toMatchObject({ HEAD_LEVEL: "HEAD", SHOULDER_LEVEL: "SHOULDERS", TRUNK_UPRIGHT: "TRUNK", HIP_LEVEL: "HIPS" });
  });
});

describe("Live body interaction", () => {
  it("supports click/tap selection", () => {
    const onSelect = vi.fn();
    render(<LiveBodyMap snapshot={snapshot()} active={null} onSelect={onSelect}/>);
    fireEvent.click(screen.getByRole("button", { name: "Shoulders region" }));
    expect(onSelect).toHaveBeenCalledWith("SHOULDERS");
  });
  it("does not crash without coordinates and mirrors one central x transform", () => {
    const { container, rerender } = render(<CameraBodyOverlay region="HEAD" state="ORANGE"/>);
    expect(container.querySelector("ellipse")).toBeNull();
    rerender(<CameraBodyOverlay region="HEAD" state="ORANGE" mirrored landmarks={{ HEAD_CENTER: { x: .2, y: .3, valid: true } }}/>);
    expect(container.querySelector("ellipse")?.getAttribute("cx")).toBe("0.8");
  });
});
