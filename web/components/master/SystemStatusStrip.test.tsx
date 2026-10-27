import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SystemStatusStrip } from "./SystemStatusStrip";

const cv = { cv_engine: true, camera_live: true, pose_receiving: true, storage_available: true, cv_fps: 22 };
const emg = { connection_state: "STREAMING", serial_port: "COM9", received_rate_hz: 998, latest_data_age_ms: 12, channels: [{}] };
const lifecycle = {
  deployment: "LOCAL_WINDOWS", application: "RUNNING",
  backend: { ready: true, managed: true }, frontend: { ready: true, managed: true },
  hardware_agent: { running: true, managed: true },
  cv: { process_running: true, camera_live: true, source: "PYTHON_ENGINE", owner: "local_agent" },
  emg: { agent_running: true, board_connected: true, signal_live: true, state: "STREAMING", port: "COM9" },
  supabase: { state: "READY" }, errors: [],
  controls: { reconnect_cv: true, reconnect_emg: true, exit: true },
};

beforeEach(() => {
  vi.stubGlobal("confirm", vi.fn(() => true));
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("lifecycle/status") ? lifecycle : url.includes("storage/status") ? { state: "READY", mode: "SUPABASE" } : url.includes("recordings/preflight") ? cv : url.includes("emg/status") ? emg : { accepted: true };
    return new Response(JSON.stringify(body), { status: init?.method === "POST" ? 202 : 200, headers: { "content-type": "application/json" } });
  }));
});

describe("FlexMap lifecycle status", () => {
  it("does not claim cloud readiness from free local disk space", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string) => {
      const url = String(input);
      const body = url.includes("storage/status") ? { state: "DATABASE_UNAVAILABLE", mode: "SUPABASE" } : url.includes("lifecycle/status") ? lifecycle : url.includes("emg/status") ? emg : cv;
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    render(<SystemStatusStrip />);
    await waitFor(() => expect(screen.getByText("Dataset storage").parentElement).toHaveTextContent("DATABASE_UNAVAILABLE"));
    expect(screen.getByText("Dataset storage").parentElement?.querySelector("i")).toHaveClass("offline");
  });
  it("keeps independent-mode controls disabled while showing a real streaming board", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string) => {
      const body = String(input).includes("lifecycle/status") ? { available: false } : String(input).includes("emg/status") ? emg : cv;
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    render(<SystemStatusStrip detailed/>);
    await screen.findByText("Hosted / independent services");
    expect(screen.getByText("Backend / external owner")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Exit FlexMap/ })).toBeDisabled();
  });
  it("shows verified local device and storage state", async () => {
    render(<SystemStatusStrip detailed/>);
    expect(await screen.findByText("Local Windows application")).toBeInTheDocument();
    expect(screen.getByText("local_agent")).toBeInTheDocument();
    expect(screen.getAllByText("Live").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Exit FlexMap/ })).toBeEnabled();
  });

  it("sends reconnect and explicit exit through authenticated proxy", async () => {
    render(<SystemStatusStrip detailed/>);
    await screen.findByText("Local Windows application");
    fireEvent.click(screen.getByRole("button", { name: /Reconnect EMG/ }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/master/data/lifecycle/reconnect/emg", { method: "POST" }));
    await waitFor(() => expect(screen.getByText("EMG reconnect requested.")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Exit FlexMap/ }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/master/data/lifecycle/stop", { method: "POST" }));
  });
});
