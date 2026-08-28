"use client";
import { memo, useEffect, useRef, useState } from "react";
import { BodyRegion } from "@/lib/bodyRegionMap";
import { DisplayLandmark, PostureState } from "@/types/posture";

type Box = { left: number; top: number; width: number; height: number };
type Points = Record<string, DisplayLandmark>;

function valid(points: Points | undefined, ...keys: string[]) { return !!points && keys.every((key) => points[key]?.valid); }

export const CameraBodyOverlay = memo(function CameraBodyOverlay({ landmarks, region, state, mirrored = false }: { landmarks?: Points; region: BodyRegion | null; state: PostureState; mirrored?: boolean }) {
  const root = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<Box>({ left: 0, top: 0, width: 0, height: 0 });
  useEffect(() => {
    const element = root.current?.parentElement;
    if (!element) return;
    const update = () => {
      const media = element.querySelector("video, img") as HTMLVideoElement | HTMLImageElement | null;
      const sourceWidth = media instanceof HTMLVideoElement ? media.videoWidth : media?.naturalWidth;
      const sourceHeight = media instanceof HTMLVideoElement ? media.videoHeight : media?.naturalHeight;
      const width = element.clientWidth, height = element.clientHeight;
      if (!sourceWidth || !sourceHeight) return setBox({ left: 0, top: 0, width, height });
      const scale = Math.min(width / sourceWidth, height / sourceHeight);
      const fittedWidth = sourceWidth * scale, fittedHeight = sourceHeight * scale;
      setBox({ left: (width - fittedWidth) / 2, top: (height - fittedHeight) / 2, width: fittedWidth, height: fittedHeight });
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update); observer?.observe(element);
    element.addEventListener("loadedmetadata", update, true); window.addEventListener("resize", update); update();
    return () => { observer?.disconnect(); element.removeEventListener("loadedmetadata", update, true); window.removeEventListener("resize", update); };
  }, []);
  if (!region || !landmarks) return <div ref={root} className="camera-body-overlay" aria-hidden="true"/>;
  const x = (key: string) => mirrored ? 1 - landmarks[key].x : landmarks[key].x;
  const y = (key: string) => landmarks[key].y;
  const point = (key: string) => `${x(key)},${y(key)}`;
  return <div ref={root} className={`camera-body-overlay overlay-${state.toLowerCase()}`} aria-hidden="true"><svg style={box} viewBox="0 0 1 1" preserveAspectRatio="none">
    {region === "HEAD" && valid(landmarks, "HEAD_CENTER") && <ellipse cx={x("HEAD_CENTER")} cy={y("HEAD_CENTER")} rx=".09" ry=".12"/>}
    {["SHOULDERS", "LEFT_SHOULDER", "RIGHT_SHOULDER"].includes(region) && valid(landmarks, "LEFT_SHOULDER", "RIGHT_SHOULDER") && <>{region !== "RIGHT_SHOULDER" && <circle cx={x("LEFT_SHOULDER")} cy={y("LEFT_SHOULDER")} r=".065"/>}{region !== "LEFT_SHOULDER" && <circle cx={x("RIGHT_SHOULDER")} cy={y("RIGHT_SHOULDER")} r=".065"/>}</>}
    {region === "TRUNK" && valid(landmarks, "LEFT_SHOULDER", "RIGHT_SHOULDER", "RIGHT_HIP", "LEFT_HIP") && <polygon points={["LEFT_SHOULDER", "RIGHT_SHOULDER", "RIGHT_HIP", "LEFT_HIP"].map(point).join(" ")}/>} 
    {region === "HIPS" && valid(landmarks, "LEFT_HIP", "RIGHT_HIP") && <path d={`M ${point("LEFT_HIP")} L ${point("RIGHT_HIP")}`}/>} 
    {region === "LEFT_ARM" && valid(landmarks, "LEFT_SHOULDER", "LEFT_ELBOW", "LEFT_WRIST") && <path d={`M ${point("LEFT_SHOULDER")} L ${point("LEFT_ELBOW")} L ${point("LEFT_WRIST")}`}/>} 
    {region === "RIGHT_ARM" && valid(landmarks, "RIGHT_SHOULDER", "RIGHT_ELBOW", "RIGHT_WRIST") && <path d={`M ${point("RIGHT_SHOULDER")} L ${point("RIGHT_ELBOW")} L ${point("RIGHT_WRIST")}`}/>} 
  </svg></div>;
});
