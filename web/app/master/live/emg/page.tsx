import { MasterFrame } from "@/components/master/MasterFrame";
import { EmgBoardSetupPage } from "@/components/master/live/EmgBoardSetupPage";
import { protectedMaster } from "@/lib/masterPage";
export const dynamic = "force-dynamic";
export default async function Page() {
  return protectedMaster(
    <MasterFrame>
      <EmgBoardSetupPage />
    </MasterFrame>,
  );
}
