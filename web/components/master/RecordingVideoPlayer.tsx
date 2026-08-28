"use client";
import{useEffect,useRef,useState}from"react";
type Info={exists:boolean;codec?:string;width?:number;height?:number;fps?:number;frame_count?:number;duration_seconds?:number;browser_compatible?:boolean;preview_status:"READY"|"MISSING"|"NOT_REQUIRED";playback_source:"preview"|"original";preview?:Info|null};
type Status={poster_exists:boolean;raw:Info;annotated:Info};
const api="/api/master/data/dataset/recordings";
export function RecordingVideoPlayer({recordingId,hasRaw,hasAnnotated}:{recordingId:string;hasRaw:boolean;hasAnnotated:boolean}){
 const video=useRef<HTMLVideoElement>(null),[variant,setVariant]=useState<"raw"|"annotated">(hasAnnotated?"annotated":"raw"),[status,setStatus]=useState<Status|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(""),[generating,setGenerating]=useState(false),position=useRef(0);
 async function loadStatus(){const r=await fetch(`${api}/${recordingId}/video-status`);if(!r.ok)throw new Error("Video status unavailable");setStatus(await r.json())}
 // eslint-disable-next-line react-hooks/exhaustive-deps
 useEffect(()=>{loadStatus().catch(e=>setError(e.message))},[recordingId]);
 // eslint-disable-next-line react-hooks/exhaustive-deps
 useEffect(()=>{setLoading(true);setError("");const timer=setTimeout(()=>setError("Video metadata did not load. A browser preview may be required."),10000);return()=>clearTimeout(timer)},[variant,status?.[variant].preview_status]);
 function change(next:"raw"|"annotated"){position.current=video.current?.currentTime||0;video.current?.pause();setVariant(next)}
 function ready(){setLoading(false);setError("");if(video.current&&position.current)video.current.currentTime=Math.min(position.current,Math.max(0,video.current.duration-.1))}
 async function generate(){setGenerating(true);setError("");const r=await fetch(`${api}/${recordingId}/video/${variant}/preview`,{method:"POST"});if(r.ok)await loadStatus();else setError((await r.json()).detail||"Preview generation failed");setGenerating(false)}
 const info=status?.[variant],available=variant==="raw"?hasRaw:hasAnnotated,src=`${api}/${recordingId}/video/${variant}`,poster=status?.poster_exists?`${api}/${recordingId}/files/preview.jpg`:undefined;
 return <section className="recording-video"><div className="master-card-head"><div><strong>Video</strong><small>{variant==="raw"?"Original clean camera recording":"CV visualization overlay"}</small></div><div className="stream-toggles"><button className={variant==="raw"?"active":""} disabled={!hasRaw} onClick={()=>change("raw")}>Raw</button><button className={variant==="annotated"?"active":""} disabled={!hasAnnotated} onClick={()=>change("annotated")}>Annotated</button></div></div>
 {available&&<div className="video-stage">{loading&&!error&&<div className="video-message">Loading video...</div>}<video key={variant+"-"+info?.preview_status} ref={video} className="detail-video" controls playsInline preload="metadata" poster={poster} src={src} onLoadedMetadata={ready} onCanPlay={ready} onError={()=>{setLoading(false);setError("VIDEO COULD NOT BE PLAYED. Unsupported codec or media request failure.")}}/></div>}
 {!available&&<p className="master-alert">This recording does not include the selected video.</p>}
 {error&&<div className="video-error"><strong>{error}</strong><div><button onClick={()=>{setError("");video.current?.load()}}>Retry</button>{info?.preview_status==="MISSING"&&<button className="primary" disabled={generating} onClick={generate}>{generating?"Preparing browser preview...":"Generate web preview"}</button>}</div></div>}
 {info&&<div className="video-details"><div><span>Playback source</span><strong>{info.playback_source==="preview"?"Browser Preview":"Original Recording"}</strong></div><div><span>Codec</span><strong>{info.playback_source==="preview"?info.preview?.codec:info.codec||"Unknown"}</strong></div><div><span>Resolution</span><strong>{info.width} x {info.height}</strong></div><div><span>FPS</span><strong>{info.fps?.toFixed(1)}</strong></div><div><span>Frames</span><strong>{info.frame_count}</strong></div><div><span>Duration</span><strong>{info.duration_seconds?.toFixed(2)} s</strong></div></div>}
 <div className="downloads"><a href={src+"?original=true&download=true"}>Download original</a>{info?.preview_status==="READY"&&<a href={src+"?download=true"}>Download web preview</a>}</div></section>
}