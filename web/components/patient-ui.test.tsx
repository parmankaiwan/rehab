import React from "react";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockSnapshot } from "@/lib/mockPosture";
import { getHeroContent } from "@/lib/patientCopy";
import { CompactPostureComponents, CORE } from "./CompactPostureComponents";
import { PatientGuidance } from "./PatientGuidance";
import { PatientHero } from "./PatientHero";

describe("patient-first interface", () => {
  it.each([
    ["GREY", false, "STEP FULLY INTO VIEW"],
    ["ORANGE", false, "ALMOST READY"],
    ["RED", false, "ADJUST YOUR POSITION"],
    ["GREEN", true, "READY TO BEGIN"],
  ] as const)("maps %s to its dynamic hero", (state, ready, title) => {
    expect(getHeroContent(state, ready).title).toBe(title);
    render(<PatientHero state={state} ready={ready} unavailable={false}/>);
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  });

  it("uses patient component labels without duplicate raw states", () => {
    render(<CompactPostureComponents snapshot={mockSnapshot("GREEN")} research={false} measurements={false}/>);
    expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Close").length).toBeGreaterThan(0);
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
  });

  it("uses literal component states in Research Mode", () => {
    render(<CompactPostureComponents snapshot={mockSnapshot("GREEN")} research measurements/>);
    expect(screen.getAllByText("GREEN").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ORANGE").length).toBeGreaterThan(0);
  });

  it("READY hides correction messages", () => {
    const snapshot = mockSnapshot("GREEN");
    snapshot.feedback = ["SIT TALL"];
    render(<PatientGuidance snapshot={snapshot} unavailable={false}/>);
    expect(screen.getByText("READY TO BEGIN")).toBeInTheDocument();
    expect(screen.queryByText(/sit tall/i)).not.toBeInTheDocument();
  });

  it("GREY shows backend tracking guidance", () => {
    const snapshot = mockSnapshot("GREY");
    render(<PatientGuidance snapshot={snapshot} unavailable={false}/>);
    expect(screen.getByText("Keep your upper body in frame")).toBeInTheDocument();
  });

  it("keeps the required core ordering", () => {
    render(<CompactPostureComponents snapshot={mockSnapshot("GREEN")} research={false} measurements={false}/>);
    const core = screen.getByRole("heading", { name: "Core" }).closest("div")?.parentElement;
    expect(core).not.toBeNull();
    const names = within(core as HTMLElement).getAllByRole("listitem").map((item) => item.querySelector("strong")?.textContent);
    expect(names).toEqual(CORE.map(([, name]) => name));
  });
});
