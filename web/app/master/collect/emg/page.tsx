import { MasterFrame } from "@/components/master/MasterFrame";
import { EmgCollectionDashboard } from "@/components/master/EmgCollectionDashboard";
import { protectedMaster } from "@/lib/masterPage";
export const dynamic = "force-dynamic";
export default async function Page(){return protectedMaster(<MasterFrame><EmgCollectionDashboard/></MasterFrame>)}
