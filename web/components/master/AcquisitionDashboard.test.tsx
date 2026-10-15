import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AcquisitionDashboard } from "./AcquisitionDashboard";

vi.mock("@/hooks/usePostureStream", () => ({
  usePostureStream: () => ({
    isStale: false,
    snapshot: { connected: true, overall_state: "GREEN", landmarks: {} },
  }),
}));
vi.mock("@/components/LiveCameraView", () => ({
  LiveCameraView: () => <div>LIVE CAMERA</div>,
}));

const studies = [
  { study_id: "STUDY-A", name: "Study Alpha", status: "ACTIVE" },
  { study_id: "STUDY-B", name: "Study Beta", status: "ACTIVE" },
];
const subjects = [
  { subject_id: "P001", affected_side: "RIGHT" },
  { subject_id: "P002", affected_side: "LEFT" },
];
const protocols = [
  {
    protocol_id: "REACHING_EMG",
    protocol_version: 2,
    display_name: "Reaching EMG",
    rehab_type: "REACHING",
    modality: "EMG",
    status: "ACTIVE",
    allowed_labels: ["reach"],
    countdown_seconds: 3,
    trial_plan: [{ label: "reach", count: 2, duration_seconds: 10 }],
  },
  {
    protocol_id: "REACHING_EMG",
    protocol_version: 1,
    display_name: "Reaching EMG",
    rehab_type: "REACHING",
    modality: "EMG",
    status: "ACTIVE",
    allowed_labels: ["reach"],
    countdown_seconds: 5,
    trial_plan: [
      { label: "reach", count: 1, duration_seconds: 5 },
      { label: "reach", count: 2, duration_seconds: 8 },
    ],
  },
  {
    protocol_id: "POSTURE_CV",
    protocol_version: 1,
    display_name: "Posture CV",
    rehab_type: "STARTING_POSTURE",
    modality: "CV",
    status: "ACTIVE",
    allowed_labels: ["acceptable_start"],
    countdown_seconds: 3,
    trial_plan: [{ label: "acceptable_start", count: 1, duration_seconds: 5 }],
  },
];
const modules = [
  {
    id: "REACHING",
    display_name: "Reaching",
    labels: ["reach", "return"],
    label_options: [
      { id: "reach", display_name: "Reach" },
      { id: "return", display_name: "Return" },
    ],
    emg_labels: ["forward_reach", "full_trial"],
    emg_label_options: [
      { id: "forward_reach", display_name: "Forward Reach" },
      { id: "full_trial", display_name: "Full Trial" },
    ],
  },
  {
    id: "STARTING_POSTURE",
    display_name: "Starting Posture",
    labels: ["acceptable_start"],
    label_options: [
      { id: "acceptable_start", display_name: "Acceptable Start" },
    ],
    emg_labels: ["ready_hold"],
    emg_label_options: [{ id: "ready_hold", display_name: "Ready Hold" }],
  },
];

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const value = url.endsWith("/studies")
        ? studies
        : url.endsWith("/subjects")
          ? subjects
          : url.endsWith("/collection-protocols")
            ? protocols
            : url.endsWith("/collections")
              ? []
              : url.endsWith("/collection-coverage")
                ? { recordings: 0, unique_subjects: 0, rows: [] }
                : url.endsWith("/dataset/settings")
                  ? { modules }
                  : {};
      return { ok: true, json: async () => value } as Response;
    }),
  );
});

afterEach(() => vi.restoreAllMocks());

describe("AcquisitionDashboard list identities", () => {
  it("offers only 3-second and 5-second protocol countdowns", async () => {
    render(<AcquisitionDashboard />);
    const selector = await screen.findByRole("combobox", {
      name: "Start countdown",
    });
    expect(selector).toHaveValue("3");
    expect(
      within(selector)
        .getAllByRole("option")
        .map((option) => (option as HTMLOptionElement).value),
    ).toEqual(["3", "5"]);
    fireEvent.change(selector, { target: { value: "5" } });
    expect(selector).toHaveValue("5");
  });
  it("renders real label options and distinct selectable protocol versions without key warnings", async () => {
    const error = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    render(<AcquisitionDashboard />);

    const protocolSelect = await screen.findByRole("combobox", {
      name: "Protocol",
    });
    const protocolOptions = within(protocolSelect).getAllByRole("option");
    expect(
      protocolOptions.map((option) => (option as HTMLOptionElement).value),
    ).toEqual(["", "REACHING_EMG:2", "REACHING_EMG:1", "POSTURE_CV:1"]);
    expect(
      within(protocolSelect).getByRole("option", { name: /Reaching EMG · V1/ }),
    ).toBeInTheDocument();
    expect(
      within(protocolSelect).getByRole("option", { name: /Reaching EMG · V2/ }),
    ).toBeInTheDocument();
    fireEvent.change(protocolSelect, { target: { value: "REACHING_EMG:1" } });
    expect(protocolSelect).toHaveValue("REACHING_EMG:1");

    const labelSelect = screen.getByRole("combobox", {
      name: "Research label",
    });
    expect(
      within(labelSelect).getByRole("option", { name: "Reach" }),
    ).toHaveValue("reach");
    expect(
      within(
        screen.getByRole("combobox", { name: "Study (optional)" }),
      ).getByRole("option", { name: /Study Beta/ }),
    ).toHaveValue("STUDY-B");
    expect(
      within(screen.getByRole("combobox", { name: "Subject" })).getByRole(
        "option",
        { name: "P002" },
      ),
    ).toHaveValue("P002");

    await waitFor(() => {
      const keyWarnings = error.mock.calls.filter(
        (call) =>
          String(call[0]).includes("unique 'key' prop") ||
          String(call[0]).includes("same key"),
      );
      expect(keyWarnings).toEqual([]);
    });
  });

  it("keeps the live camera visible under a server countdown and offers cancel", async () => {
    const active = {
      collection_id: "COL-1",
      subject_id: "P001",
      session_id: "SESSION-1",
      protocol_id: "POSTURE_CV",
      protocol_version: 1,
      protocol_snapshot: protocols[2],
      rehab_type: "STARTING_POSTURE",
      modality: "CV",
      status: "ACTIVE",
      current_trial_id: "TRIAL-1",
      revision: 1,
      trials: [
        {
          trial_id: "TRIAL-1",
          trial_number: 1,
          research_label: "acceptable_start",
          duration_seconds: 10,
          duration_mode: "FIXED",
          countdown_seconds: 5,
          countdown_remaining: 5,
          state: "COUNTDOWN",
          attempt_number: 1,
          active_modality: "CV",
          quality_warnings: [],
          recording_ids: { CV: "CV-1" },
        },
      ],
    };
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      const value = url.endsWith("/studies")
        ? studies
        : url.endsWith("/subjects")
          ? subjects
          : url.endsWith("/collection-protocols")
            ? protocols
            : url.endsWith("/collections/COL-1/preflight")
              ? { overall: "PASS", checked_at: "now", checks: [] }
              : url.endsWith("/collections/COL-1") ||
                  url.includes("/cancel-countdown")
                ? active
                : url.endsWith("/collections")
                  ? [active]
                  : url.endsWith("/collection-coverage")
                    ? { recordings: 0, unique_subjects: 0, rows: [] }
                    : url.endsWith("/dataset/settings")
                      ? { modules }
                      : {};
      return { ok: true, json: async () => value } as Response;
    });
    render(<AcquisitionDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: "Open" }));
    expect(await screen.findByText("LIVE CAMERA")).toBeInTheDocument();
    expect(
      within(screen.getByRole("status")).getByText("GET READY"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("status")).getByText("5"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel countdown" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/trials/TRIAL-1/cancel-countdown"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
