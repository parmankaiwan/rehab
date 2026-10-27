import { describe, expect, it } from "vitest";
import type { NormalizedLandmark } from "@mediapipe/tasks-vision";
import { browserCameraErrorMessage, browserSnapshotFromLandmarks } from "./useBrowserPose";

function pose(): NormalizedLandmark[] {
  const points = Array.from({ length: 25 }, () => ({ x: .5, y: .5, z: 0, visibility: .99, presence: .99 }));
  Object.assign(points[0], { x: .5, y: .18 });
  Object.assign(points[11], { x: .35, y: .35 });
  Object.assign(points[12], { x: .65, y: .35 });
  Object.assign(points[13], { x: .27, y: .5 });
  Object.assign(points[14], { x: .73, y: .5 });
  Object.assign(points[15], { x: .2, y: .67 });
  Object.assign(points[16], { x: .8, y: .67 });
  Object.assign(points[23], { x: .4, y: .72 });
  Object.assign(points[24], { x: .6, y: .72 });
  return points;
}

describe("browser pose compatibility snapshot", () => {
  it("gives actionable diagnostics without claiming a permission failure is a model failure", () => {
    expect(browserCameraErrorMessage(new DOMException("denied", "NotAllowedError"))).toContain("Allow Camera");
    expect(browserCameraErrorMessage(new DOMException("busy", "NotReadableError"))).toContain("Close other camera apps");
    expect(browserCameraErrorMessage(new DOMException("missing", "NotFoundError"))).toContain("No camera");
    expect(browserCameraErrorMessage(new Error("Model download failed"))).toBe("Model download failed");
  });
  it("maps a fully visible centered pose into the existing ready contract", () => {
    const result = browserSnapshotFromLandmarks(pose(), 12, 20);
    expect(result.ready).toBe(true);
    expect(result.overall_state).toBe("GREEN");
    expect(result.tracking_quality).toBe("GOOD");
    expect(result.landmarks?.LEFT_WRIST.valid).toBe(true);
    expect(result.components.BODY_TRACKING_COMPLETE.state).toBe("GREEN");
  });

  it("never marks a pose ready when a required arm landmark is not visible", () => {
    const points = pose();
    points[15].visibility = .1;
    const result = browserSnapshotFromLandmarks(points, 13, 20);
    expect(result.ready).toBe(false);
    expect(result.components.LEFT_ARM_VISIBLE.state).toBe("GREY");
    expect(result.feedback[0]).toContain("visible");
  });
});
