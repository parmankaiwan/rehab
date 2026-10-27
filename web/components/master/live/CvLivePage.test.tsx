import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CvLivePage } from "./CvLivePage";

vi.mock("@/hooks/useBrowserPose", () => ({ useBrowserPose: () => ({ state: "CAMERA_READY", snapshot: null, videoRef: { current: null }, error: "", delegate: "CPU", inferenceCount: 8, restart: vi.fn() }) }));
vi.mock("@/hooks/usePostureStream", () => ({ usePostureStream: () => ({ connectionState: "CONNECTING", snapshot: null, isStale: false, reconnect: vi.fn() }) }));
vi.mock("@/components/LiveCameraView", () => ({ LiveCameraView: () => <div>Camera view</div> }));

it("does not call a working camera unavailable just because no person is tracked", () => {
  render(<CvLivePage />);
  expect(screen.getByRole("button", { name: "Browser MediaPipe" })).toHaveClass("active");
  expect(screen.getByText("Camera ready — waiting for pose")).toBeTruthy();
  expect(screen.getByText("READY (CPU)")).toBeTruthy();
  expect(screen.getByText("8")).toBeTruthy();
  expect(screen.queryByText("Browser camera unavailable")).toBeNull();
});

it("keeps the separate Python engine available only when explicitly selected", () => {
  render(<CvLivePage />);
  expect(screen.getByRole("button", { name: "FlexMap Engine" })).not.toHaveClass("active");
  fireEvent.click(screen.getByRole("button", { name: "FlexMap Engine" }));
  expect(screen.getByRole("button", { name: "FlexMap Engine" })).toHaveClass("active");
  expect(screen.getByText("CV connection unavailable")).toBeTruthy();
});
