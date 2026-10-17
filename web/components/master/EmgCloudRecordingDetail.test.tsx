import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EmgCloudRecordingDetail } from "./EmgCloudRecordingDetail";

const detail={recording_id:"EMG-1",dataset_id:"EDS-1",research_label:"rest",subject_code:"SYNTHETIC",duration_seconds:1,sample_rate_hz:1000,signal_units:"ADC_COUNTS",channel_count:1,review_status:"REVIEW_REQUIRED",training_eligible:false,excluded:false,artifacts:[]};

describe("EMG vault recording review",()=>{
  beforeEach(()=>vi.stubGlobal("fetch",vi.fn(async(input:string,init?:RequestInit)=>{
    const url=String(input);
    if(url.includes("waveform"))return{ok:true,json:async()=>({raw_units:"ADC_COUNTS",sample_rate_hz:1000,samples:[{timestamp_ms:"0",channel_1:"100"},{timestamp_ms:"1",channel_1:"120"}]})};
    if(url.endsWith("cloud-datasets"))return{ok:true,json:async()=>[{dataset_id:"EDS-1",labels:[{name:"rest"},{name:"active"}]}]};
    if(init?.method==="PATCH")return{ok:true,json:async()=>({...detail,...JSON.parse(String(init.body))})};
    if(init?.method==="POST")return{ok:true,json:async()=>({...detail,trashed_at:"2026-10-17T00:00:00Z"})};
    return{ok:true,json:async()=>detail};
  })));

  it("renders the saved waveform and persists explicit approval",async()=>{
    render(<EmgCloudRecordingDetail id="EMG-1"/>);
    await screen.findByRole("img",{name:"Waveform for channel_1"});
    fireEvent.change(screen.getByLabelText("Research label"),{target:{value:"active"}});
    fireEvent.click(screen.getByLabelText("Eligible for training after approval"));
    fireEvent.click(screen.getByRole("button",{name:/Approve/}));
    await waitFor(()=>expect(fetch).toHaveBeenCalledWith(expect.stringContaining("EMG-1"),expect.objectContaining({method:"PATCH",body:expect.stringContaining('"review_status":"APPROVED"')})));
  });
});
