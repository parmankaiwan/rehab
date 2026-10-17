import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserSampleDetail } from "./BrowserSampleDetail";

const sample={sample_id:"SMP-1",dataset_id:"DS-1",label_at_capture:"lean",reviewed_label:null,sample_type:"STILL",source:"BROWSER_MEDIAPIPE",subject_id:"SYNTHETIC",capture_state:"COMPLETE",technical_quality:"GOOD",tracking_quality:"GOOD",review_status:"REVIEW_REQUIRED",training_eligible:false,artifact_manifest:[]};

describe("CV vault sample review",()=>{
  beforeEach(()=>vi.stubGlobal("fetch",vi.fn(async(input:string,init?:RequestInit)=>{
    const url=String(input);
    if(url.endsWith("/DS-1"))return{ok:true,json:async()=>({labels:[{name:"lean",display_name:"Lean",archived:false},{name:"aligned",display_name:"Aligned",archived:false}]})};
    if(init?.method==="PATCH")return{ok:true,json:async()=>({...sample,...JSON.parse(String(init.body))})};
    if(init?.method==="POST")return{ok:true,json:async()=>({...sample,trashed_at:"2026-10-17T00:00:00Z"})};
    return{ok:true,json:async()=>sample};
  })));

  it("approves a relabeled sample and can move it to recoverable trash",async()=>{
    render(<BrowserSampleDetail id="SMP-1"/>);
    await screen.findByText("Research review");
    fireEvent.change(screen.getByLabelText("Reviewed label"),{target:{value:"aligned"}});
    fireEvent.click(screen.getByLabelText("Eligible for training after approval"));
    fireEvent.click(screen.getByRole("button",{name:/Approve/}));
    await waitFor(()=>expect(fetch).toHaveBeenCalledWith(expect.stringContaining("SMP-1"),expect.objectContaining({method:"PATCH",body:expect.stringContaining('"review_status":"APPROVED"')})));
    fireEvent.click(screen.getByRole("button",{name:/Move to trash/}));
    await waitFor(()=>expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/trash"),expect.objectContaining({method:"POST"})));
  });
});
