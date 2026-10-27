import time
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.emg.parser import parse_serial_line
from backend.emg.schemas import ChannelConfig,ConnectRequest,RemoteEmgBatch
from pydantic import ValidationError
from backend.emg.service import EmgService
from backend.dataset_config import DatasetSettings

def test_parser_preserves_supported_formats_and_malformed_isolated():
 assert parse_serial_line('512','VALUE_ONLY',1)==(None,None,[512.0])
 assert parse_serial_line('12,512','TIMESTAMP_VALUE',1)==(None,12.0,[512.0])
 assert parse_serial_line('1,2,3,4','CSV_CHANNELS',4)==(None,None,[1.,2.,3.,4.])
 assert parse_serial_line('7,12,1,2','SEQUENCE_TIMESTAMP_CSV',2)==(7,12.0,[1.,2.])
 assert parse_serial_line('bad,data','CSV_CHANNELS',2) is None

@pytest.mark.parametrize('value',['nan','NaN','inf','-inf','1e999'])
def test_parser_rejects_nonfinite_channels_and_device_timestamps(value):
 assert parse_serial_line(value,'VALUE_ONLY',1) is None
 assert parse_serial_line('1,'+value,'CSV_CHANNELS',2) is None
 assert parse_serial_line(value+',-3','TIMESTAMP_VALUE',1) is None
 assert parse_serial_line(value+',-3,4','TIMESTAMP_CSV_CHANNELS',2) is None
 assert parse_serial_line('7,'+value+',-3','SEQUENCE_TIMESTAMP_CSV',1) is None
 assert parse_serial_line('12,-3.5','TIMESTAMP_VALUE',1)==(None,12.,[-3.5])

def test_remote_batches_preserve_signed_values_and_reject_mismatched_or_nonfinite_data():
 assert RemoteEmgBatch(source_port='TEST',channel_count=1,samples=[{'values':[-2.5]}]).samples[0].values==[-2.5]
 with pytest.raises(ValidationError):RemoteEmgBatch(source_port='TEST',channel_count=2,samples=[{'values':[1.]}])
 with pytest.raises(ValidationError):RemoteEmgBatch(source_port='TEST',samples=[{'values':[float('nan')]}])
 with pytest.raises(ValidationError):RemoteEmgBatch(source_port='TEST',samples=[{'values':[1.],'device_timestamp':float('inf')}])
 with pytest.raises(ValidationError):RemoteEmgBatch(source_port='TEST',expected_sample_rate_hz=float('inf'))

def test_mock_buffer_is_bounded_and_four_channel_1000hz(tmp_path):
 settings=DatasetSettings(root=tmp_path/'vault',labels_path=tmp_path/'labels.json');settings.labels_path.write_text('{}')
 service=EmgService(settings);channels=[ChannelConfig(internal_id=f'channel_{i}',display_name=f'Channel {i}') for i in range(1,5)]
 service.connect(ConnectRequest(transport_type='MOCK',expected_sample_rate_hz=1000,channels=channels));time.sleep(.12);status=service.status();batch=service.batch(0,500);service.disconnect()
 assert status['channel_count']==4 and status['valid_samples']>=60 and len(batch['samples'])<=500
 assert all(len(x['channels'])==4 for x in batch['samples']) and service.samples.maxlen==60000

def test_emg_master_api_is_protected(monkeypatch):
 monkeypatch.setenv('FLEXMAP_MASTER_INTERNAL_TOKEN','secret')
 assert TestClient(app).get('/api/master/emg/status').status_code==403
