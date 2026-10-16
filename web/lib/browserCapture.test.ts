import { describe, expect, it } from "vitest";
import { captureQuality, isEditableTarget, selectRecorderFormat } from "./browserCapture";

describe("browser capture helpers", () => {
  it("selects a supported MIME type without changing its container extension", () => {
    expect(selectRecorderFormat((value) => value === "video/webm;codecs=vp8")).toEqual({ mimeType: "video/webm;codecs=vp8", extension: ".webm" });
    expect(selectRecorderFormat(() => false)).toBeNull();
  });

  it("does not require a GREEN classifier state for technically usable data", () => {
    const observations = [{ valid: true, snapshot: { tracking_quality: "GOOD", overall_state: "RED" } }] as never;
    expect(captureQuality(observations).technicalQuality).toBe("GOOD");
  });

  it("ignores capture shortcuts while typing", () => {
    const input = document.createElement("input");
    expect(isEditableTarget(input)).toBe(true);
    expect(isEditableTarget(document.createElement("div"))).toBe(false);
  });
});
