import { createElement } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useBrowserPose } from "./useBrowserPose";

const model = vi.hoisted(() => ({ resolve: vi.fn(), create: vi.fn() }));
vi.mock("@mediapipe/tasks-vision", () => ({ FilesetResolver: { forVisionTasks: model.resolve }, PoseLandmarker: { createFromOptions: model.create } }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function Harness() {
  const pose = useBrowserPose(true);
  return createElement("div", null, createElement("video", { ref: pose.videoRef }), createElement("span", null, pose.state));
}

function setup() {
  const stop = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }) } });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 200, json: async () => ({ accepted: true, mode: "HOSTED" }) }));
  model.resolve.mockResolvedValue({});
  return stop;
}

it("releases the physical camera when both MediaPipe delegates fail", async () => {
  const stop = setup();
  model.create.mockRejectedValue(new Error("model unavailable"));
  const view = render(createElement(Harness));
  await waitFor(() => expect(view.getByText("UNAVAILABLE")).toBeTruthy());
  expect(stop).toHaveBeenCalledTimes(1);
  expect(view.container.querySelector("video")?.srcObject).toBeNull();
  expect(model.create).toHaveBeenCalledTimes(2);
});

it("closes a model that finishes initialization after the page unmounts", async () => {
  const stop = setup();
  let finish!: (value: unknown) => void;
  const close = vi.fn();
  model.create.mockReset().mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = render(createElement(Harness));
  await waitFor(() => expect(model.create).toHaveBeenCalledTimes(1));
  view.unmount();
  await act(async () => { finish({ close }); });
  expect(stop).toHaveBeenCalledTimes(1);
  expect(close).toHaveBeenCalledTimes(1);
});
