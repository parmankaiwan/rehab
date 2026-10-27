import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { EmgResearchStudies } from "./EmgResearchStudies";

beforeEach(()=>vi.stubGlobal("fetch",vi.fn(async(input:string,init?:RequestInit)=>{
 if(input.endsWith("research/catalog"))return new Response(JSON.stringify({functions:["MOVING_PEAK","NARROW_PEAK"]}));
 if(input.endsWith("/experiments")&&!init)return new Response("[]");
 if(input.endsWith("research/experiments"))return new Response(JSON.stringify({experiment_id:"EMGR-test",status:"COMPLETED",progress:1,configuration:JSON.parse(init!.body as string),results:null}));
 if(input.endsWith("research/test-device"))return new Response(JSON.stringify({source_type:"TEST_DEVICE",waveform:{channel_1:[1,2],channel_2:[3,4],channel_3:[5,6]},timestamp_us:[0,1000],physical_hardware:"NOT TESTED"}));
 return new Response("{}",{status:404});
})));

it("submits reproducible mathematical studies with distinct tasks and constrained variants",async()=>{
 render(<EmgResearchStudies/>);
 expect(await screen.findByRole("option",{name:"MOVING_PEAK"})).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"Run Study A"}));
 await waitFor(()=>expect(screen.getByText(/COMPLETED/)).toBeInTheDocument());
 const calls=vi.mocked(fetch).mock.calls;const sent=JSON.parse(calls.find(([p])=>String(p).endsWith("research/experiments"))![1]!.body as string);
 expect(sent.study).toBe("A");expect(sent.simulation.seed).toBe(42);expect(sent.optimize).toBe(true);
 fireEvent.click(screen.getByRole("tab",{name:"Mathematics-Informed Learning"}));
 expect(screen.getByRole("option",{name:"Spatial integral regression"})).toBeInTheDocument();
 expect(screen.getByText("GQ REGULARIZED")).toBeInTheDocument();
});

it("renders the isolated three-channel test-device waveform",async()=>{
 render(<EmgResearchStudies/>);
 fireEvent.click(screen.getByRole("tab",{name:"Multichannel Test Device"}));
 fireEvent.click(screen.getByRole("button",{name:"Run TEST DEVICE"}));
 expect(await screen.findByRole("img",{name:"TEST DEVICE waveform"})).toBeInTheDocument();
 expect(screen.getAllByText(/PHYSICAL HARDWARE REQUIRED/).length).toBeGreaterThan(0);
});
