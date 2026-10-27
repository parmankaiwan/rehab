"""Software-only acceptance on an isolated backend and synthetic data directory.

Run with the project Python environment. Opens localhost:8001 only, never USB.
Outputs aggregate metrics and generated artifact paths, never credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid

import httpx

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def main():
    from backend.emg_research import FUNCTIONS_V2
    folder=ROOT/"data"/"runtime"/("research-acceptance-"+uuid.uuid4().hex[:12]);folder.mkdir(parents=True)
    token=secrets.token_hex(32);environment={**os.environ,"FLEXMAP_MASTER_INTERNAL_TOKEN":token,"FLEXMAP_DATASET_ROOT":str(folder/"vault"),"FLEXMAP_ML_DURABLE_STORAGE_ENABLED":"false","FLEXMAP_SUPABASE_SECRET_KEY":"","FLEXMAP_SUPABASE_SYNC_ENABLED":"false"}
    headers={"X-FlexMap-Master-Token":token};origin="http://127.0.0.1:8001";api=origin+"/api/master/ml/emg-comparison";log=(folder/"server.log").open("w",encoding="utf-8")
    process=None
    def start():
        process=subprocess.Popen([sys.executable,"-m","uvicorn","backend.app:app","--host","127.0.0.1","--port","8001"],cwd=ROOT,env=environment,stdout=log,stderr=log)
        for _ in range(120):
            if process.poll() is not None:raise RuntimeError("Acceptance server exited; inspect isolated log")
            try:
                if httpx.get(origin+"/health",timeout=1).status_code==200:return process
            except httpx.HTTPError:pass
            time.sleep(.5)
        raise RuntimeError("Acceptance server health timeout")
    def stop(process):
        if process and process.poll() is None:
            if os.name=="nt":subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True,check=False)
            else:process.terminate();process.wait(timeout=20)
    try:
        # Never stop an unrelated service occupying the acceptance port.
        import socket
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1",8001))==0:raise RuntimeError("Port 8001 occupied; no process was stopped")
        process=start();client=httpx.Client(headers=headers,timeout=60)
        assert httpx.get(api+"/research/catalog").status_code==403
        requests=[
            {"study":"A","simulation":{"frames":24,"seed":821},"functions":FUNCTIONS_V2,"sweep_parameter":"peak_width","sweep_values":[.08,.25,.5],"trials":2,"optimization_candidates":6,"held_out_families":["NARROW_PEAK"]},
            {"study":"B","task":"INTEGRAL_REGRESSION","subjects":24,"epochs":20,"frames":32,"seeds":[42,73],"models":["MLP","RANDOM_FOREST"],"lambdas":[.01,.1,1]},
            {"study":"B","task":"RESEARCH_LABEL_CLASSIFICATION","subjects":24,"epochs":8,"frames":32,"seeds":[42,73],"models":["MLP","CNN_1D","TCN","GRU","RANDOM_FOREST"],"lambdas":[.1]},
        ]
        saved=[];summaries=[]
        for index,configuration in enumerate(requests):
            response=client.post(api+"/research/experiments",json=configuration);response.raise_for_status();identifier=response.json()["experiment_id"]
            for _ in range(600):
                response=client.get(api+f"/experiments/{identifier}");response.raise_for_status();item=response.json()
                if item["status"] in {"FAILED","CANCELLED","COMPLETED"}:break
                time.sleep(.5)
            if item["status"]!="COMPLETED":raise RuntimeError(f"Study failed: {item.get('error') or item['status']}")
            digest=hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest();saved.append((identifier,digest))
            result=item["results"]
            for ext in ("json","csv","zip"):
                export=client.get(api+f"/experiments/{identifier}/export.{ext}");export.raise_for_status();(folder/f"study-{index+1}.{ext}").write_bytes(export.content)
            summary={"id":identifier,"study":result["study"],"task":result.get("task"),"runtime_seconds":result["runtime_seconds"],"artifact_count":len(item["artifact_manifest"])}
            if result["study"]=="A":summary.update({"trajectories":len(result["scenarios"]),"sweep":result["sweep_summary"],"optimized":{k:v["selected"] for k,v in result["optimization"].items()}})
            else:summary.update({"models_executed":len(result["results"]),"comparison":[{"model":r["model"],"variant":r["variant"],"seed":r["seed"],"test":r["test"],"weights":r["weights"]} for r in result["results"]]})
            summaries.append(summary)
            print(json.dumps({"completed":index+1,"id":identifier,"runtime_seconds":result["runtime_seconds"]}),flush=True)
        device=client.post(api+"/research/test-device",json={"channels":[{"channel_id":f"channel_{i}"} for i in (1,2,3)]});device.raise_for_status();device=device.json()
        client.close();stop(process);process=None;time.sleep(1);process=start();client=httpx.Client(headers=headers,timeout=60)
        for identifier,digest in saved:
            reopened=client.get(api+f"/experiments/{identifier}");reopened.raise_for_status();assert hashlib.sha256(json.dumps(reopened.json(),sort_keys=True).encode()).hexdigest()==digest
        reopened=client.get(api+"/research/test-device/"+device["test_recording_id"]);reopened.raise_for_status();assert reopened.json()["recording_integrity"]==device["recording_integrity"]
        assert httpx.get(api+f"/experiments/{saved[0][0]}").status_code==403
        report={"status":"PASS","source":"SYNTHETIC MATHEMATICAL DATA","hardware":"NOT TESTED","restart_integrity":"PASS","unauthorized_requests":"BLOCKED_AS_EXPECTED","test_device":device["recording_integrity"],"studies":summaries,"artifacts_directory":str(folder)}
        (folder/"acceptance.json").write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps({"status":"PASS","report":str(folder/"acceptance.json")}),flush=True)
    finally:
        stop(process);log.close()


if __name__=="__main__":main()
