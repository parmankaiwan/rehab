from __future__ import annotations
from collections import deque
import numpy as np

class EmgSignalQualityMonitor:
 def __init__(self,max_samples=10000):self.max_samples=max_samples;self.channels:dict[str,deque[float]]={}
 def reset(self):self.channels={}
 def accept(self,channels:dict[str,float]):
  for key,value in channels.items():self.channels.setdefault(key,deque(maxlen=self.max_samples)).append(float(value))
 def report(self,sample_rate_hz:float|None,adc_bits:int|None)->dict:
  reports={};warnings=[]
  for key,buffer in self.channels.items():
   values=np.asarray(buffer,dtype=float);n=len(values);entry={"sample_count":n,"clipped_sample_ratio":None,"flatline":None,"near_constant":None,"baseline_drift_counts":None,"powerline_50hz_ratio":None,"powerline_60hz_ratio":None,"transient_ratio":None,"warnings":[]}
   if n:
    std=float(np.std(values));span=float(np.ptp(values));entry["standard_deviation_counts"]=std;entry["peak_to_peak_counts"]=span
    entry["flatline"]=bool(n>=20 and span==0);entry["near_constant"]=bool(n>=100 and std<0.5)
    if adc_bits:
     maximum=2**adc_bits-1;margin=max(1,maximum*.005);entry["clipped_sample_ratio"]=float(np.mean((values<=margin)|(values>=maximum-margin)))
     if entry["clipped_sample_ratio"]>.01:entry["warnings"].append("SATURATION_OR_CLIPPING")
    if n>=100:
     half=n//2;entry["baseline_drift_counts"]=float(abs(np.mean(values[-half:])-np.mean(values[:half])))
     if adc_bits and entry["baseline_drift_counts"]>(2**adc_bits-1)*.05:entry["warnings"].append("LARGE_BASELINE_DRIFT")
     diffs=np.abs(np.diff(values));threshold=max(10,std*6);entry["transient_ratio"]=float(np.mean(diffs>threshold)) if len(diffs) else 0
     if entry["transient_ratio"]>.01:entry["warnings"].append("EXCESSIVE_TRANSIENTS_OR_MOTION_ARTIFACT")
    if sample_rate_hz and n>=max(128,int(sample_rate_hz)):
     centered=values-np.mean(values);spectrum=np.abs(np.fft.rfft(centered))**2;freqs=np.fft.rfftfreq(n,1/sample_rate_hz);total=float(np.sum(spectrum[1:])) or 1
     for frequency,name in ((50,"powerline_50hz_ratio"),(60,"powerline_60hz_ratio")):
      mask=(freqs>=frequency-1)&(freqs<=frequency+1);entry[name]=float(np.sum(spectrum[mask])/total)
     if max(entry["powerline_50hz_ratio"] or 0,entry["powerline_60hz_ratio"] or 0)>.2:entry["warnings"].append("POWERLINE_CONTAMINATION_ESTIMATE")
    if entry["flatline"] or entry["near_constant"]:entry["warnings"].append("FLATLINE_OR_CHANNEL_DISCONNECTED")
   reports[key]=entry;warnings.extend(f"{key}: {warning}" for warning in entry["warnings"])
  return {"signal_quality_version":"1.0","scope":"TECHNICAL_SIGNAL_CHARACTERISTICS_NOT_CLINICAL","channels":reports,"warnings":warnings,"limitations":["Powerline and artifact metrics are engineering estimates.","Timing quality is reported separately as acquisition quality."]}