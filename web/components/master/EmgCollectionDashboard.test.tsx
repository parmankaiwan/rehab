import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EmgCollectionDashboard } from "./EmgCollectionDashboard";

vi.mock("@/hooks/useEmgStream",()=>({useEmgStream:()=>({samples:[],status:null,clear:vi.fn()})}));
const response=(data:unknown)=>Promise.resolve({ok:true,json:()=>Promise.resolve(data)} as Response);

describe("EmgCollectionDashboard",()=>{
 beforeEach(()=>{sessionStorage.clear();vi.stubGlobal("fetch",vi.fn((input:string|URL|Request)=>{const url=String(input);if(url.endsWith("/subjects"))return response([]);if(url.endsWith("/collection-protocols"))return response([]);if(url.endsWith("/emg/hardware-profiles"))return response([]);if(url.endsWith("/collections"))return response([]);if(url.endsWith("/collection-coverage"))return response({recordings:0,unique_subjects:0,protocol_distribution:{},hardware_distribution:{},baseline_coverage:{required:0,complete:0},ml_readiness:{eligible_recordings:0,unique_subjects:0,mock_excluded:true}});if(url.endsWith("/emg/status"))return response({connection_state:"DISCONNECTED",channel_count:0,channels:[],received_rate_hz:0});throw new Error(`Unexpected request ${url}`)}))});
 it("opens the dedicated nine-step EMG collection setup",async()=>{render(<EmgCollectionDashboard/>);expect(await screen.findByRole("heading",{name:/EMG research collection/i})).toBeInTheDocument();fireEvent.click(screen.getByRole("button",{name:/New EMG collection/i}));expect(screen.getByRole("heading",{name:/New EMG collection/i})).toBeInTheDocument();expect(screen.getByText("Baseline",{selector:".emgc-stepper span"})).toBeInTheDocument();expect(screen.getByText("Preflight",{selector:".emgc-stepper span"})).toBeInTheDocument();expect(screen.getByRole("link",{name:/Configure board and channel map/i})).toHaveAttribute("href","/master/live/emg");await waitFor(()=>expect(fetch).toHaveBeenCalled())});
});
