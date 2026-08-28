import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MasterLogin } from "./MasterLogin";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

describe("Master login interface", () => {
  beforeEach(() => { refresh.mockReset(); vi.restoreAllMocks(); });

  it("uses an accessible password field and reports incorrect credentials", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ success: false, error: "Invalid password" }) }));
    render(<MasterLogin/>);
    const field = screen.getByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    fireEvent.change(field, { target: { value: "wrong" } });
    fireEvent.submit(field.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect password.");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("refreshes the protected server page after successful login", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ success: true }) }));
    render(<MasterLogin/>);
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock Master Dashboard" }));
    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  });
});
