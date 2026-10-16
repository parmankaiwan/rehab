import { Suspense } from "react";
import { CvCollectionStudio } from "@/components/master/CvCollectionStudio";
import { MasterFrame } from "@/components/master/MasterFrame";
import { protectedMaster } from "@/lib/masterPage";

export const dynamic = "force-dynamic";
export default async function Page() { return protectedMaster(<MasterFrame><Suspense fallback={<p>Loading Studio…</p>}><CvCollectionStudio/></Suspense></MasterFrame>); }
