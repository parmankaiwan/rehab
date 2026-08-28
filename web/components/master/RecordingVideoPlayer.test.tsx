import{fireEvent,render,screen,waitFor}from"@testing-library/react";
import{beforeEach,describe,expect,it,vi}from"vitest";
import{RecordingVideoPlayer}from"./RecordingVideoPlayer";
const info={exists:true,codec:"FMP4",width:640,height:480,fps:20,frame_count:108,duration_seconds:5.4,browser_compatible:false,preview_status:"READY" as const,playback_source:"preview" as const,preview:{codec:"VP80"}};
describe("RecordingVideoPlayer",()=>{
 beforeEach(()=>{
  vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>{});
  vi.stubGlobal("fetch",vi.fn(async()=>({ok:true,json:async()=>({poster_exists:true,raw:info,annotated:info})})));
 });
 it("shows loading, poster, details, and switches variants",async()=>{
  const{container}=render(<RecordingVideoPlayer recordingId="REC-1" hasRaw hasAnnotated/>);
  expect(screen.getByText("Loading video...")).toBeInTheDocument();
  await waitFor(()=>expect(screen.getByText("Browser Preview")).toBeInTheDocument());
  const video=container.querySelector("video")!;
  expect(video.getAttribute("poster")).toContain("preview.jpg");
  fireEvent.loadedMetadata(video);
  fireEvent.click(screen.getByRole("button",{name:"Raw"}));
  expect(container.querySelector("video")?.getAttribute("src")).toContain("/video/raw");
  expect(screen.getByRole("link",{name:"Download original"})).toBeInTheDocument();
 });
});
