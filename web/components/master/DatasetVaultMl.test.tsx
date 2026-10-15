import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DatasetVault } from "./DatasetVault";
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
const rows = [
  {
    recording_id: "REC-001",
    subject_id: "P001",
    session_id: "S1",
    rehab_type: "REACHING",
    modality: "CV",
    research_label: "FORWARD",
    review_status: "APPROVED",
    technical_quality: "GOOD",
    training_eligible: true,
    eligibility_reason: "ELIGIBLE",
    is_mock: false,
    created_at: "2026-01-01",
  },
  {
    recording_id: "REC-002",
    subject_id: "P002",
    session_id: "S2",
    rehab_type: "REACHING",
    modality: "CV",
    research_label: "RETURN",
    review_status: "APPROVED",
    technical_quality: "GOOD",
    training_eligible: true,
    eligibility_reason: "ELIGIBLE",
    is_mock: false,
    created_at: "2026-01-02",
  },
];
const stats = {
  total_samples: 2,
  training_eligible: 2,
  excluded: 0,
  storage_bytes: 100,
  label_counts: { FORWARD: 1, RETURN: 1 },
  subject_counts: { P001: 1, P002: 1 },
  quality_counts: { GOOD: 2 },
};
describe("Dataset Vault ML selection", () => {
  beforeEach(() => {
    push.mockReset();
    const mock = vi.fn(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("vault-recordings"))
          return { ok: true, json: async () => rows };
        if (url.includes("dataset/stats"))
          return { ok: true, json: async () => stats };
        if (url.includes("supabase/status"))
          return {
            ok: true,
            json: async () => ({
              configured: true,
              enabled: true,
              reachable: true,
              upload_artifacts: false,
              project_host: "project.supabase.co",
              table: "flexmap_dataset_recordings",
              bucket: "flexmap-dataset",
            }),
          };
        if (url.endsWith("supabase/sync") && init?.method === "POST")
          return {
            ok: true,
            json: async () => ({ total: 2, synced: 2, failed: 0, disabled: 0, results: [] }),
          };
        if (url.includes("vault-recordings/REC-") && init?.method === "DELETE")
          return { ok: true, json: async () => ({ success: true }) };
        if (url.endsWith("datasets/from-vault"))
          return {
            ok: true,
            json: async () => ({
              dataset_version_id: "DATASET-1",
              name: "REACHING_CV",
              status: "DRAFT",
              rehab_type: "REACHING",
              modality: "CV",
              recording_ids: ["REC-001", "REC-002"],
              source_query: {},
              label_distribution: { FORWARD: 1, RETURN: 1 },
              subject_distribution: { P001: 1, P002: 1 },
              quality_distribution: { GOOD: 2 },
              health: { state: "READY", errors: [], warnings: [] },
              created_at: "2026-01-01",
              mock_included: false,
            }),
          };
        if (url.endsWith("DATASET-1/freeze") && init?.method === "POST")
          return {
            ok: true,
            json: async () => ({ dataset_version_id: "DATASET-1" }),
          };
        return { ok: false, json: async () => ({}) };
      },
    );
    vi.stubGlobal("fetch", mock as unknown as typeof fetch);
  });
  it("freezes selected eligible recordings and navigates with the dataset attached", async () => {
    render(<DatasetVault />);
    await screen.findByText("REC-001");
    fireEvent.click(
      screen.getByRole("button", { name: /select for training/i }),
    );
    fireEvent.click(screen.getByLabelText("Select REC-001"));
    fireEvent.click(screen.getByLabelText("Select REC-002"));
    expect(screen.getByText("2 recordings selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /use for training/i }));
    expect(
      await screen.findByText("Create training dataset"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /freeze & continue/i }));
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/master/ml/train?dataset=DATASET-1"),
    );
  });
  it("confirms and deletes a recording from the rightmost row action", async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    render(<DatasetVault />);
    await screen.findByText("REC-001");
    fireEvent.click(screen.getByRole("button", { name: "Delete REC-001" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("REC-001"));
    await waitFor(() =>
      expect(screen.queryByText("REC-001")).not.toBeInTheDocument(),
    );
    expect(fetch).toHaveBeenCalledWith(
      "/api/master/data/ml/vault-recordings/REC-001?confirm=REC-001",
      { method: "DELETE" },
    );
  });
  it("shows the private Supabase mirror and syncs the vault", async () => {
    render(<DatasetVault />);
    expect(await screen.findByText("Connected to project.supabase.co")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /sync vault/i }));
    expect(await screen.findByText("2 of 2 recordings synced.")).toBeInTheDocument();
  });
});
