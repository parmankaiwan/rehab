import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EmgValidationLab } from "./EmgValidationLab";

vi.mock("@/hooks/useEmgStream", () => ({
  useEmgStream: () => ({
    samples: [],
    status: {
      connection_state: "STREAMING",
      serial_port: "COM9",
      baud_rate: 115200,
      protocol: "CSV_CHANNELS",
      channel_count: 1,
      channels: [{ internal_id: "channel_1", display_name: "EMG 1" }],
      received_rate_hz: 998,
      valid_samples: 200,
      invalid_packets: 0,
      recorder_drops: 0,
      is_mock: false,
      recording_state: "IDLE",
    },
    clear: vi.fn(),
  }),
}));
vi.mock("./EmgChart", () => ({
  EmgChart: () => <canvas aria-label="Live EMG waveform" />,
}));
const profile = {
  schema_version: "1.0",
  hardware_profile_id: "HWP-1",
  profile_version: 2,
  display_name: "ESP32 Board",
  transport_type: "USB_SERIAL",
  channel_count: 1,
  expected_sample_rate_hz: 1000,
  device_timestamp_supported: true,
  device_sequence_supported: true,
  adc_bits: 12,
  raw_representation: "ADC_COUNTS_UNSIGNED",
  archived: false,
  created_at: "now",
  updated_at: "now",
};
const ids = [
  "usb_detection",
  "serial_connection",
  "stream",
  "channels",
  "baseline",
  "fixed_trial",
  "manual_trial",
  "event_markers",
  "review",
  "retry",
  "interruption",
  "reconnect",
  "long_run",
  "dataset",
  "raw_integrity",
  "processing",
  "training_eligibility",
];
const tests = Object.fromEntries(
  ids.map((id) => [
    id,
    { state: "NOT_RUN", metrics: {}, warnings: [], failures: [] },
  ]),
);
const run = {
  validation_run_id: "VAL-TEST-001",
  hardware_profile_id: "HWP-1",
  hardware_profile_version: 2,
  status: "RUNNING",
  selected_port: "COM9",
  baud_rate: 115200,
  serial_protocol: "CSV_CHANNELS",
  configured_sample_rate_hz: 1000,
  started_at: "now",
  tests,
  warnings: [],
  failures: [],
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      let value: unknown = {};
      if (url.endsWith("/hardware-profiles")) value = [profile];
      else if (url.includes("/devices"))
        value = [
          {
            port: "COM9",
            description: "CP210x",
            manufacturer: "Silicon Labs",
            is_usb: true,
          },
        ];
      else if (url.endsWith("/baselines")) value = [{ baseline_id: "BASE-1" }];
      else if (url.endsWith("/status"))
        value = {
          connection_state: "STREAMING",
          serial_port: "COM9",
          baud_rate: 115200,
          protocol: "CSV_CHANNELS",
          received_rate_hz: 998,
          latest_data_age_ms: 4,
          valid_samples: 200,
          invalid_packets: 0,
          channels: [],
        };
      else if (url.endsWith("/serial-diagnostics"))
        value = {
          bytes_received: 12000,
          valid_packets: 200,
          invalid_packets: 0,
        };
      else if (url.includes("/commissioning/profiles/"))
        value = {
          validated: false,
          warning:
            "CURRENT HARDWARE CONFIGURATION DIFFERS FROM LAST VALIDATION",
        };
      else if (url.includes("/commissioning/runs") && init?.method === "POST")
        value = run;
      else if (url.includes("/commissioning/runs")) value = [];
      return { ok: true, json: async () => value } as Response;
    }),
  );
});

describe("EMG hardware validation", () => {
  it("renders every commissioning step and physical interruption boundary", async () => {
    render(<EmgValidationLab />);
    await waitFor(() =>
      expect(screen.getByText(/HWP-1 v2/)).toBeInTheDocument(),
    );
    for (const label of [
      "USB Detection",
      "Serial Connection",
      "Stream Check",
      "Channel Check",
      "Baseline",
      "Fixed Trial",
      "Manual Trial",
      "Interruption",
      "Reconnect",
      "Long Run",
      "Dataset Check",
      "Final Report",
    ])
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    expect(screen.getByText("Three rest baselines")).toBeInTheDocument();
    expect(screen.getByText("30-second stream")).toBeInTheDocument();
    expect(screen.getByText("UNPLUG BOARD NOW")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByText(/CURRENT HARDWARE CONFIGURATION DIFFERS/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Live EMG waveform")).toBeInTheDocument();
  });
  it("creates a persistent run and exposes tests, diagnostics, and final report", async () => {
    render(<EmgValidationLab />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Start validation run/ }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Start validation run/ }),
    );
    await waitFor(() =>
      expect(screen.getAllByText("VAL-TEST-001").length).toBeGreaterThan(0),
    );
    expect(
      screen.getByRole("button", { name: /Run USB detection/ }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: /Run Serial connection/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Export diagnostics/ }),
    ).toBeEnabled();
    expect(
      screen.getByText("Final hardware validation report"),
    ).toBeInTheDocument();
    expect(screen.getByText("Validation history")).toBeInTheDocument();
  });
});
