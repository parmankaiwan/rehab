import { CvCollectionHome } from "@/components/master/CvCollectionHome";
import { MasterFrame } from "@/components/master/MasterFrame";
import { protectedMaster } from "@/lib/masterPage";

export const dynamic = "force-dynamic";

export default async function Page() {
  return protectedMaster(<MasterFrame><CvCollectionHome/></MasterFrame>);
}
