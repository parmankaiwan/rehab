import { MasterFrame } from "@/components/master/MasterFrame";
import { EmgProtocolBuilder } from "@/components/master/EmgProtocolBuilder";
import { protectedMaster } from "@/lib/masterPage";
export const dynamic = "force-dynamic";
export default async function Page(){return protectedMaster(<MasterFrame><EmgProtocolBuilder/></MasterFrame>)}
