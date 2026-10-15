"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Activity, ArrowLeft, Boxes, BrainCircuit, ChevronLeft, ChevronRight, ClipboardList, Database, FlaskConical, Home, Menu, Radio, ScanLine, Settings, Users, Video, X } from "lucide-react";
import { MasterHeader } from "./MasterHeader";
type NavItem={href:string;label:string;icon:LucideIcon;exact?:boolean;future?:boolean};
type NavGroup={label:string;items:NavItem[]};
const groups:NavGroup[]=[
 {label:"Workspace",items:[{href:"/master",label:"Overview",icon:Home,exact:true}]},
 {label:"Live sensors",items:[{href:"/master/live/cv",label:"CV Live",icon:Video},{href:"/master/live/emg",label:"EMG Live",icon:Activity}]},
 {label:"Collection",items:[{href:"/master/collect",label:"Data Collection",icon:ClipboardList,exact:true},{href:"/master/collect/emg",label:"EMG Research",icon:Activity},{href:"/master/collect/protocols",label:"Protocols",icon:ClipboardList},{href:"/master/sessions",label:"Sessions",icon:Users},{href:"/master/cv-data",label:"CV Collection",icon:ScanLine},{href:"/master/emg",label:"EMG Collection",icon:Radio}]},
 {label:"Research data",items:[{href:"/master/dataset",label:"Dataset Vault",icon:Database},{href:"/master/ml/datasets",label:"Dataset Versions",icon:Database}]},
 {label:"Machine learning",items:[{href:"/master/ml/train",label:"Training",icon:BrainCircuit},{href:"/master/ml/runs",label:"Training Runs",icon:FlaskConical},{href:"/master/ml/models",label:"Model Registry",icon:Boxes}]},
 {label:"Platform",items:[{href:"/master/system",label:"System",icon:Settings}]},
];
export function MasterFrame({children}:{children:React.ReactNode}){const path=usePathname(),[open,setOpen]=useState(false),[compact,setCompact]=useState(false);return <div className={`master-shell research-shell${compact?" nav-compact":""}${open?" nav-open":""}`}><MasterHeader/><button className="master-mobile-menu" onClick={()=>setOpen(!open)} aria-expanded={open} aria-label={open?"Close research navigation":"Open research navigation"}>{open?<X/>:<Menu/>}<span>Menu</span></button><div className="master-frame"><aside className="master-side" aria-label="Research navigation"><div className="master-side-brand"><span className="brand-mark" aria-hidden="true"><i/><i/><i/></span><div><strong>FLEXMAP</strong><small>Research Console</small></div></div>{groups.map(group=><div className="master-nav-group" key={group.label}><span>{group.label}</span>{group.items.map(item=>{const active=item.exact?path===item.href:path.startsWith(item.href),Icon=item.icon;return <Link key={item.href} href={item.href} title={item.label} onClick={()=>setOpen(false)} className={active?"active":""} aria-current={active?"page":undefined}><Icon/><b>{item.label}</b>{item.future&&<small>Future</small>}</Link>})}</div>)}<span className="master-nav-spacer"/><Link href="/" className="master-patient-link"><ArrowLeft/><b>Patient View</b></Link><button className="master-collapse" onClick={()=>setCompact(!compact)} aria-label={compact?"Expand sidebar":"Collapse sidebar"}>{compact?<ChevronRight/>:<ChevronLeft/>}<span>{compact?"Expand":"Collapse"}</span></button></aside><button className="master-nav-scrim" aria-label="Close navigation" onClick={()=>setOpen(false)}/><main className="master-content">{children}</main></div></div>}
