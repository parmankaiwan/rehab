import Link from "next/link";
import { Activity } from "lucide-react";
import { DatasetVault } from "@/components/master/DatasetVault";
import { EmgCloudDatasetVault } from "@/components/master/EmgCloudDatasetVault";
import { MasterFrame } from "@/components/master/MasterFrame";
import { protectedMaster } from "@/lib/masterPage";

export const dynamic = "force-dynamic";

export default async function Page() {
  return protectedMaster(
    <MasterFrame>
      <section>
        <div className="ml-page-head">
          <div>
            <span className="eyebrow">Electromyography research storage</span>
            <h1>EMG Dataset Vault</h1>
            <p className="master-lead">Only EMG waveforms, channels, hardware metadata, processing results, and review records appear here.</p>
          </div>
          <Link className="primary" href="/master/emg"><Activity />Back to EMG Collection</Link>
        </div>
        <EmgCloudDatasetVault />
        <div className="collection-legacy">
          <span className="eyebrow">Existing local FlexMap recordings</span>
          <DatasetVault modalityFilter="EMG" title="EMG recordings" />
        </div>
      </section>
    </MasterFrame>,
  );
}
