"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Download, FlaskConical, Play, Square } from "lucide-react";

type Model = { id:string; name:string; category:string; input_representation:string; estimated_cost:string; advantage:string; eligible:boolean; ineligible_reason?:string };
type Catalog = { models:Model[]; functions:string[]; hardware_limit:string };
type Matrix = { labels:string[]; values:number[][] };
type Metric = { macro_f1:number; macro_f1_ci95?:{lower:number;upper:number}|null; independent_subjects:number; uncertainty_status:string; balanced_accuracy:number; confusion_matrix:Matrix };
type History = { epoch:number; training_loss:number; validation_loss?:number };
type Result = { model:string; mathematical_method:string; validation:Metric; test:Metric; training_seconds:number; model_size_bytes:number; training_history:History[] };
type Experiment = { experiment_id:string; status:string; stage:string; progress:number; error?:string; results?:{ results:Result[]; limitations:string[]; ranking_statement:string; data_readiness:{display_message:string;ranking_eligible:boolean} } };
type Simulation = { time:number[]; mean_curve:number[]; gq_curve:number[]; reference_curve:number[]; methods:Record<string,{rmse:number}>; comparison:{winner:string;gq_rmse_improvement_percent:number|null} };

const api = "/api/master/data/ml/emg-comparison";
const pct = (value:number) => `${(value * 100).toFixed(1)}%`;

function PolylineChart({ series, label }:{ series:{values:number[];className:string}[]; label:string }) {
  const width=760,height=210,all=series.flatMap(item=>item.values),lo=Math.min(...all),hi=Math.max(...all),span=hi-lo||1;
  const points=(values:number[])=>values.map((value,index)=>`${index/Math.max(1,values.length-1)*width},${height-(value-lo)/span*height}`).join(" ");
  return <div className="emgcmp-chart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>{series.map(item=><polyline key={item.className} className={item.className} points={points(item.values)}/>)}</svg></div>;
}

function SignalChart({ data }:{ data:Simulation }) {
  return <><PolylineChart label="Synthetic signal comparison" series={[{values:data.reference_curve,className:"reference"},{values:data.mean_curve,className:"mean"},{values:data.gq_curve,className:"gq"}]}/><div className="emgcmp-legend"><span className="reference">Dense reference</span><span className="mean">Arithmetic mean</span><span className="gq">Gaussian quadrature</span></div></>;
}

function LearningChart({ history }:{ history:History[] }) {
  return <><h3>Best ranked learning curve</h3><PolylineChart label="Training and validation loss" series={[{values:history.map(x=>x.training_loss),className:"mean"},{values:history.map(x=>x.validation_loss??x.training_loss),className:"gq"}]}/><div className="emgcmp-legend"><span className="mean">Training loss</span><span className="gq">Validation loss</span></div></>;
}

export function EmgComparisonDashboard() {
  const [catalog,setCatalog]=useState<Catalog|null>(null),[saved,setSaved]=useState<Experiment[]>([]);
  const [selected,setSelected]=useState(["LOGISTIC_REGRESSION","RANDOM_FOREST","MLP"]),[methods,setMethods]=useState(["ARITHMETIC_MEAN","GAUSSIAN_QUADRATURE"]);
  const [fn,setFn]=useState("CENTRAL_PEAK"),[simulation,setSimulation]=useState<Simulation|null>(null),[run,setRun]=useState<Experiment|null>(null),[error,setError]=useState(""),[amplitudes,setAmplitudes]=useState([.2,1,.4]);

  useEffect(()=>{Promise.all([fetch(`${api}/catalog`),fetch(`${api}/experiments`)]).then(async([catalogResponse,historyResponse])=>{if(!catalogResponse.ok)throw new Error("Comparison catalog is unavailable");setCatalog(await catalogResponse.json());if(historyResponse.ok)setSaved(await historyResponse.json())}).catch(reason=>setError(String(reason)))},[]);
  const refresh=useCallback(async(id:string)=>{const response=await fetch(`${api}/experiments/${id}`);if(!response.ok)throw new Error("Experiment status is unavailable");const item=await response.json();setRun(item);if(!["QUEUED","RUNNING","CANCEL_REQUESTED"].includes(item.status))setSaved(current=>[item,...current.filter(x=>x.experiment_id!==id)])},[]);
  useEffect(()=>{if(!run||!["QUEUED","RUNNING","CANCEL_REQUESTED"].includes(run.status))return;const timer=setInterval(()=>refresh(run.experiment_id).catch(reason=>setError(String(reason))),800);return()=>clearInterval(timer)},[run,refresh]);
  const arithmetic=useMemo(()=>amplitudes.reduce((a,b)=>a+b,0)/3,[amplitudes]),gaussian=useMemo(()=>amplitudes[0]*5/18+amplitudes[1]*4/9+amplitudes[2]*5/18,[amplitudes]);
  const toggle=(value:string,list:string[],setter:(next:string[])=>void)=>setter(list.includes(value)?list.filter(item=>item!==value):[...list,value]);

  async function simulate(){setError("");const response=await fetch(`${api}/simulation`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({function:fn,order:3,frames:120})}),body=await response.json();if(!response.ok)throw new Error(body.detail||"Simulation failed");setSimulation(body)}
  async function train(){setError("");const response=await fetch(`${api}/experiments`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:`${fn.replaceAll("_"," ")} comparison`,simulation_function:fn,models:selected,methods})}),body=await response.json();if(!response.ok){setError(typeof body.detail==="string"?body.detail:body.detail?.message||"Training could not start");return}setRun(body)}
  async function cancel(){if(run)await fetch(`${api}/experiments/${run.experiment_id}/cancel`,{method:"POST"}).then(()=>refresh(run.experiment_id))}
  function exportFigure(kind:"svg"|"png"){const source=document.querySelector<SVGSVGElement>(".emgcmp-chart svg");if(!source)return;const copy=source.cloneNode(true) as SVGSVGElement;copy.setAttribute("xmlns","http://www.w3.org/2000/svg");const blob=new Blob([new XMLSerializer().serializeToString(copy)],{type:"image/svg+xml"}),url=URL.createObjectURL(blob),save=(href:string,extension:string)=>{const link=document.createElement("a");link.href=href;link.download=`flexmap-emg-method-comparison.${extension}`;link.click()};if(kind==="svg"){save(url,"svg");URL.revokeObjectURL(url);return}const image=new Image();image.onload=()=>{const canvas=document.createElement("canvas");canvas.width=1520;canvas.height=420;canvas.getContext("2d")?.drawImage(image,0,0,canvas.width,canvas.height);canvas.toBlob(output=>{if(output){const png=URL.createObjectURL(output);save(png,"png");URL.revokeObjectURL(png)}URL.revokeObjectURL(url)},"image/png")};image.src=url}

  const best=run?.results?.results[0];
  return <section className="emgcmp-page">
    <header className="emgcmp-head"><div><span className="eyebrow">EMG mathematical processing {" · "} development-only research</span><h1>Mean vs Gaussian Quadrature</h1><p>Inspect real equations, simulate known spatial functions, and run paired model comparisons with the same subjects, split, seed, and features.</p></div><Activity/></header>
    {error&&<div className="emgcmp-alert">{error}</div>}
    <div className="emgcmp-safety"><strong>Hardware eligibility</strong><span>{catalog?.hardware_limit||"Checking channel geometry..."}</span></div>

    <article className="emgcmp-card"><div className="emgcmp-card-title"><span>1</span><div><h2>Interactive three-channel demonstration</h2><p>Primary order n=3: nodes -sqrt(3/5), 0, +sqrt(3/5); normalized average weights 5/18, 4/9, 5/18.</p></div></div>
      <div className="emgcmp-geometry" aria-label="Three-channel Gauss-Legendre geometry"><i style={{left:"11.3%"}}>A<small>-0.7746</small></i><i style={{left:"50%"}}>B<small>0</small></i><i style={{left:"88.7%"}}>C<small>+0.7746</small></i></div>
      <div className="emgcmp-sliders">{amplitudes.map((value,index)=><label key={index}>Channel {index+1}<input aria-label={`Channel ${index+1} amplitude`} type="range" min="0" max="1.5" step=".01" value={value} onChange={event=>setAmplitudes(items=>items.map((item,i)=>i===index?Number(event.target.value):item))}/><b>{value.toFixed(2)}</b></label>)}</div>
      <div className="emgcmp-equations"><div><small>Arithmetic mean</small><strong>{arithmetic.toFixed(4)}</strong><code>(A + B + C) / 3</code></div><div><small>Gaussian quadrature average</small><strong>{gaussian.toFixed(4)}</strong><code>5A/18 + 4B/9 + 5C/18</code></div><div><small>Observed difference</small><strong>{(gaussian-arithmetic).toFixed(4)}</strong><code>No accuracy claim without reference truth</code></div></div>
    </article>

    <article className="emgcmp-card"><div className="emgcmp-card-title"><span>2</span><div><h2>Simulation laboratory</h2><p>Dense numerical integration provides known reference truth. These are synthetic signals, not human EMG.</p></div></div>
      <div className="emgcmp-toolbar"><label>Spatial function<select value={fn} onChange={event=>setFn(event.target.value)}>{catalog?.functions.map(value=><option key={value}>{value}</option>)}</select></label><button className="primary" onClick={()=>simulate().catch(reason=>setError(String(reason)))}><Play/>Run simulation</button>{simulation&&<><button onClick={()=>exportFigure("svg")}><Download/>SVG figure</button><button onClick={()=>exportFigure("png")}><Download/>PNG figure</button></>}</div>
      {simulation&&<><SignalChart data={simulation}/><div className="emgcmp-metrics"><div><small>Mean RMSE</small><strong>{simulation.methods.ARITHMETIC_MEAN.rmse.toFixed(5)}</strong></div><div><small>GQ RMSE</small><strong>{simulation.methods.GAUSSIAN_QUADRATURE.rmse.toFixed(5)}</strong></div><div><small>Actual winner</small><strong>{simulation.comparison.winner.replaceAll("_"," ")}</strong></div></div></>}
    </article>

    <article className="emgcmp-card"><div className="emgcmp-card-title"><span>3</span><div><h2>Matched multi-model experiment</h2><p>All methods use one subject-safe outer split. Learned weights use training subjects only; raw multichannel has a larger information budget.</p></div></div>
      <div className="emgcmp-toolbar"><label>Source<select aria-label="Experiment source"><option>Synthetic simulation</option><option disabled>Real EMG Vault - requires eligible 3+ channel dataset</option></select></label></div>
      <div className="emgcmp-presets"><button onClick={()=>setSelected(["LOGISTIC_REGRESSION","RANDOM_FOREST","MLP"])}>Recommended models</button><button onClick={()=>setSelected(catalog?.models.filter(model=>model.eligible).map(model=>model.id)||[])}>Select all eligible</button><button onClick={()=>setSelected([])}>Clear</button></div>
      <div className="emgcmp-methods">{["ARITHMETIC_MEAN","GAUSSIAN_QUADRATURE","LEARNED_SPATIAL_WEIGHTS","RAW_MULTICHANNEL"].map(value=><label className={methods.includes(value)?"selected":""} key={value}><input type="checkbox" checked={methods.includes(value)} onChange={()=>toggle(value,methods,setMethods)}/>{value.replaceAll("_"," ")}</label>)}</div>
      <div className="emgcmp-models">{catalog?.models.map(model=><button key={model.id} disabled={!model.eligible} className={selected.includes(model.id)?"selected":""} onClick={()=>toggle(model.id,selected,setSelected)}><span>{model.category}</span><strong>{model.name}</strong><small>{model.input_representation}</small><small>{model.eligible?`${model.estimated_cost} cost · ${model.advantage}`:model.ineligible_reason}</small></button>)}</div>
      <div className="emgcmp-runbar"><button className="primary" disabled={!selected.length||!methods.length||!!run&&["QUEUED","RUNNING","CANCEL_REQUESTED"].includes(run.status)} onClick={train}><FlaskConical/>Train selected models</button>{run&&<><div><b>{run.status.replaceAll("_"," ")}</b><span>{run.stage.replaceAll("_"," ")}</span><progress max="1" value={run.progress}/></div>{["QUEUED","RUNNING"].includes(run.status)&&<button onClick={cancel}><Square/>Cancel</button>}</>}</div>
      {!!saved.length&&<div className="emgcmp-saved"><strong>Saved experiments</strong>{saved.slice(0,6).map(item=><button key={item.experiment_id} onClick={()=>refresh(item.experiment_id)}>{item.experiment_id}<small>{item.status}</small></button>)}</div>}
    </article>

    {run?.results&&<article className="emgcmp-card"><div className="emgcmp-card-title"><span>4</span><div><h2>Comparison results</h2><p>{run.results.ranking_statement}. Held-out synthetic test results are reported separately.</p></div></div>
      <div className="emgcmp-alert"><strong>{run.results.data_readiness.display_message}</strong><br/>Real Vault evidence is not eligible for classification or spatial GQ. Synthetic results below are software-development evidence only.</div>
      <div className="table-wrap"><table><thead><tr><th>{run.results.data_readiness.ranking_eligible?"Rank":"Order"}</th><th>Model</th><th>Method</th><th>Validation F1 (subject bootstrap 95% CI)</th><th>Test F1</th><th>Test balanced accuracy</th><th>Training</th><th>Size</th></tr></thead><tbody>{run.results.results.map((row,index)=><tr key={`${row.model}-${row.mathematical_method}`}><td>{index+1}</td><td>{row.model.replaceAll("_"," ")}</td><td>{row.mathematical_method.replaceAll("_"," ")}</td><td>{pct(row.validation.macro_f1)}{row.validation.macro_f1_ci95?<small>{pct(row.validation.macro_f1_ci95.lower)}–{pct(row.validation.macro_f1_ci95.upper)}</small>:<small>CI omitted: {row.validation.independent_subjects} independent subjects</small>}</td><td>{pct(row.test.macro_f1)}</td><td>{pct(row.test.balanced_accuracy)}</td><td>{row.training_seconds.toFixed(3)} s</td><td>{(row.model_size_bytes/1024).toFixed(1)} KB</td></tr>)}</tbody></table></div>
      {best&&best.training_history.length>0&&<LearningChart history={best.training_history}/>} {best&&<div className="emgcmp-confusion"><h3>Best ranked held-out confusion matrix</h3><div>{best.test.confusion_matrix.labels.map((label,index)=><span key={label}><b>{label}</b>{best.test.confusion_matrix.values[index].map((value,column)=><i key={column}>{value}</i>)}</span>)}</div></div>}
      <div className="emgcmp-exports"><a href={`${api}/experiments/${run.experiment_id}/export.json`}><Download/>JSON</a><a href={`${api}/experiments/${run.experiment_id}/export.csv`}><Download/>CSV</a><a href={`${api}/experiments/${run.experiment_id}/export.zip`}><Download/>ISEF package</a></div><p className="emgcmp-limit">{run.results.limitations.join(" · ")}</p>
    </article>}
  </section>;
}
