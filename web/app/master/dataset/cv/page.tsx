import Link from "next/link";
import { Camera } from "lucide-react";
import { BrowserDatasetVault } from "@/components/master/BrowserDatasetVault";
import { DatasetVault } from "@/components/master/DatasetVault";
import { MasterFrame } from "@/components/master/MasterFrame";
import { protectedMaster } from "@/lib/masterPage";

export const dynamic = "force-dynamic";

export default async function Page() {
  return protectedMaster(
    <MasterFrame>
      <section>
        <div className="ml-page-head">
          <div>
            <span className="eyebrow">Computer vision research storage</span>
            <h1>CV Dataset Vault</h1>
            <p className="master-lead">Only CV images, videos, landmarks, measurements, and review records appear here.</p>
          </div>
          <Link className="primary" href="/master/cv-data"><Camera />Back to CV Collection</Link>
        </div>
        <BrowserDatasetVault />
        <div className="collection-legacy">
          <span className="eyebrow">Existing FlexMap Engine recordings</span>
          <DatasetVault modalityFilter="CV" title="CV recordings" />
        </div>
      </section>
    </MasterFrame>,
  );
}
