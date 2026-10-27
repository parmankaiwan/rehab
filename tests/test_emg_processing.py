import csv,hashlib,json,math,time
import numpy as np
import pytest
from pydantic import ValidationError
from backend.emg.signal_processing import ChannelProcessor,EmgProcessingConfig,EmgProcessingPipeline
from backend.emg.signal_quality import EmgSignalQualityMonitor
from backend.emg.schemas import BaselineRequest,ChannelConfig,ConnectRequest,RecordingRequest
from backend.emg.service import EmgService
from backend.dataset_config import DatasetSettings


def samples(rate=1000,n=2000,frequency=70):
 return [{"sequence_id":i+1,"host_timestamp_ns":i*1_000_000,"channels":{"channel_1":2048+100*math.sin(2*math.pi*frequency*i/rate)}} for i in range(n)]

def test_nyquist_and_config_hash():
 with pytest.raises(ValidationError):EmgProcessingConfig(enabled=True,processing_sample_rate_hz=500,bandpass_high_hz=450)
 a=EmgProcessingConfig();b=EmgProcessingConfig(rms_window_ms=50)
 assert a.hash==EmgProcessingConfig().hash and a.hash!=b.hash

def test_signed_raw_rectification_and_analytical_rms_preserve_input_units():
 cfg=EmgProcessingConfig(enabled=True,dc_removal_enabled=False,bandpass_enabled=False,rms_window_ms=4)
 processor=ChannelProcessor(cfg);raw=[-3.,4.,-3.,4.];before=raw.copy()
 rows=processor.process_batch(raw)
 assert raw==before
 assert [row['raw'] for row in rows]==raw
 assert [row['filtered'] for row in rows]==raw
 assert [row['rectified'] for row in rows]==[3.,4.,3.,4.]
 assert rows[-1]['rms']==pytest.approx(math.sqrt(12.5))
 # Multiplication by a physical-unit conversion factor scales every amplitude
 # representation by the same factor; this does not invent sensor calibration.
 scaled=ChannelProcessor(cfg).process_batch([x*.001 for x in raw])
 for a,b in zip(rows,scaled):
  for key in ('raw','filtered','rectified','rms'):assert b[key]==pytest.approx(a[key]*.001)

@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_configuration_and_samples_are_rejected_without_poisoning_dsp(value):
 with pytest.raises(ValidationError):EmgProcessingConfig(processing_sample_rate_hz=value)
 processor=ChannelProcessor(EmgProcessingConfig())
 with pytest.raises(ValueError):processor.process(value)
 with pytest.raises(ValueError):processor.process_batch([1,value])
 assert all(v is None or math.isfinite(v) for v in processor.process(1).values())

def test_causal_chunk_consistency_rectification_and_rms():
 cfg=EmgProcessingConfig(enabled=True,notch_enabled=False)
 whole=EmgProcessingPipeline(cfg).process_rows(samples())
 split=EmgProcessingPipeline(cfg);part=split.process_rows(samples()[:1000]);part+= [x for row in samples()[1000:] if (x:=split.process(row))]
 assert np.allclose([x['channels']['channel_1']['filtered'] for x in whole],[x['channels']['channel_1']['filtered'] for x in part])
 assert all(x['channels']['channel_1']['rectified']>=0 for x in whole)
 assert whole[-1]['channels']['channel_1']['rms']>0

def test_notch_reduces_50hz_response():
 raw=samples(frequency=50)
 off=EmgProcessingPipeline(EmgProcessingConfig(enabled=True,bandpass_enabled=False,dc_removal_enabled=False,notch_enabled=False)).process_rows(raw)
 on=EmgProcessingPipeline(EmgProcessingConfig(enabled=True,bandpass_enabled=False,dc_removal_enabled=False,notch_enabled=True,notch_frequency_hz=50)).process_rows(raw)
 off_rms=np.std([x['channels']['channel_1']['filtered'] for x in off[1000:]])
 on_rms=np.std([x['channels']['channel_1']['filtered'] for x in on[1000:]])
 assert on_rms < off_rms*.25

def test_signal_quality_clipping_flatline_and_powerline():
 clipping=EmgSignalQualityMonitor();[clipping.accept({'channel_1':0 if i%2 else 4095}) for i in range(1000)];report=clipping.report(1000,12)['channels']['channel_1'];assert report['clipped_sample_ratio']==1
 flat=EmgSignalQualityMonitor();[flat.accept({'channel_1':2048}) for _ in range(1000)];assert flat.report(1000,12)['channels']['channel_1']['flatline']
 power=EmgSignalQualityMonitor();[power.accept({'channel_1':2048+100*math.sin(2*math.pi*50*i/1000)}) for i in range(2000)];assert power.report(1000,12)['channels']['channel_1']['powerline_50hz_ratio']>.8

def test_processing_failure_isolated():
 pipeline=EmgProcessingPipeline(EmgProcessingConfig(enabled=True));pipeline.processors['channel_1']=object()
 assert pipeline.process(samples(n=1)[0]) is None and not pipeline.config.enabled and pipeline.error

def test_reprocessing_preserves_raw_and_multiple_runs(tmp_path):
 settings=DatasetSettings(root=tmp_path/'vault',labels_path=tmp_path/'labels.json');settings.labels_path.write_text('{}');service=EmgService(settings);module=service.registry.modules[0];rid='EMG-TEST-000001';base=settings.rehab_dir/module.slug/'emg'/'recordings'/rid;base.mkdir(parents=True)
 raw=base/'emg_raw.csv'
 with raw.open('w',newline='',encoding='utf-8') as f:
  writer=csv.DictWriter(f,fieldnames=['sequence_id','host_timestamp_ns','relative_timestamp_ms','device_sequence_id','device_timestamp','channel_1','valid']);writer.writeheader();[writer.writerow({'sequence_id':i+1,'host_timestamp_ns':i*1_000_000,'relative_timestamp_ms':i,'device_sequence_id':'','device_timestamp':'','channel_1':2048+math.sin(i),'valid':True}) for i in range(200)]
 meta={'recording_id':rid,'rehab_type':module.id,'rehab_slug':module.slug,'subject_id':'TEST','session_id':None,'research_label':module.emg_labels[0],'affected_side':'UNKNOWN','created_at_utc':'2026-01-01T00:00:00Z','duration_actual':.2,'sample_count':200,'channel_count':1,'measured_sample_rate_hz':1000,'technical_quality':'GOOD','is_mock':True,'interrupted':False,'adc_bits':12};(base/'metadata.json').write_text(json.dumps(meta));(base/'quality_report.json').write_text('{}')
 relative=str(base.relative_to(settings.root)).replace('\\','/');values=(rid,module.id,module.slug,'TEST',None,module.emg_labels[0],'UNKNOWN',meta['created_at_utc'],.2,200,1,1000,'GOOD',1,0,0,0,relative,raw.stat().st_size)
 with service._db() as db:db.execute('INSERT INTO emg_recordings VALUES('+','.join('?' for _ in values)+')',values)
 before=hashlib.sha256(raw.read_bytes()).hexdigest();a=service.reprocess(rid,EmgProcessingConfig(enabled=True));b=service.reprocess(rid,EmgProcessingConfig(enabled=True,rms_window_ms=50));after=hashlib.sha256(raw.read_bytes()).hexdigest()
 assert before==after==a['source_raw_sha256']==b['source_raw_sha256'];assert a['processing_run_id']!=b['processing_run_id'];assert len(service.processing_runs(rid))==2
def test_rest_baseline_saves_raw_summary_quality_and_no_threshold(tmp_path):
 settings=DatasetSettings(root=tmp_path/'vault',labels_path=tmp_path/'labels.json');settings.labels_path.write_text('{}');service=EmgService(settings);module=service.registry.modules[0];channel=ChannelConfig(internal_id='channel_1',display_name='Triceps')
 service.connect(ConnectRequest(transport_type='MOCK',expected_sample_rate_hz=1000,channels=[channel]));service.apply_processing_config(EmgProcessingConfig(enabled=True));time.sleep(.1);service._baseline(BaselineRequest(rehab_type=module.id,subject_id='TEST',duration_seconds=1),module);service.disconnect()
 baseline=service.baseline_review;folder=settings.rehab_dir/module.slug/'emg'/'baselines'/baseline['baseline_id']
 assert (folder/'emg_raw.csv').is_file() and (folder/'baseline_summary.json').is_file() and (folder/'signal_quality_report.json').is_file()
 assert baseline['summary']['channel_1']['rms_mean'] is not None and 'activation_threshold' not in json.dumps(baseline).lower()
 assert RecordingRequest(rehab_type=module.id,subject_id='TEST',research_label=module.emg_labels[0],duration_seconds=1,consent_recorded=True,baseline_id=baseline['baseline_id']).baseline_id==baseline['baseline_id']
