import { EmgCloudRecordingDetail } from "@/components/master/EmgCloudRecordingDetail";
import { MasterFrame } from "@/components/master/MasterFrame";
import { protectedMaster } from "@/lib/masterPage";

export const dynamic = "force-dynamic";

export default async function Page({ params }:{ params:Promise<{id:string}> }) {
  const {id}=await params;
  return protectedMaster(<MasterFrame><EmgCloudRecordingDetail id={id}/></MasterFrame>);
}
