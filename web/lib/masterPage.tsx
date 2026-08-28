import { cookies } from "next/headers";
import { MasterLogin } from "@/components/master/MasterLogin";
import { MASTER_COOKIE, verifyMasterSession } from "@/lib/masterAuth";

export async function protectedMaster(content: React.ReactNode) {
  const jar = await cookies();
  return verifyMasterSession(jar.get(MASTER_COOKIE)?.value) ? content : <MasterLogin/>;
}
