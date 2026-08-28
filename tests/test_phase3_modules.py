import json
from backend.dataset_vault import DatasetVault
from backend.dataset_config import DatasetSettings
from backend.rehab_modules import RehabModuleRegistry
from tests.test_dataset_vault import make_temp

def config(tmp_path):
 labels=tmp_path/'labels.json';labels.write_text('{}',encoding='utf-8')
 return DatasetSettings(root=tmp_path/'vault',labels_path=labels,countdown_seconds=0)

def test_registry_has_safe_unique_scopes():
 registry=RehabModuleRegistry(__import__('pathlib').Path('config/rehab_modules.json'))
 assert [m.slug for m in registry.modules]==['starting_posture','reaching','elbow_extension','trunk_control']
 assert len({m.id for m in registry.modules})==len(registry.modules)
 assert registry.validate_label('REACHING','reach').slug=='reaching'
 try: registry.validate_label('REACHING','acceptable_start')
 except ValueError: pass
 else: raise AssertionError('cross-module label accepted')

def test_legacy_stays_unassigned_until_confirmed_move(tmp_path):
 vault=DatasetVault(config(tmp_path));rid=vault.new_recording_id();make_temp(vault,rid);vault.save_temp(rid)
 before=vault.get(rid);assert before['rehab_type']=='UNASSIGNED' and before['relative_path'].startswith('recordings/')
 try:vault.assign_rehab(rid,'STARTING_POSTURE','acceptable_start',False)
 except ValueError:pass
 else:raise AssertionError('assignment did not require confirmation')
 after=vault.assign_rehab(rid,'STARTING_POSTURE','acceptable_start',True)
 assert after['rehab_slug']=='starting_posture' and after['training_eligible']==0 and after['review_status']=='REVIEW'
 assert after['relative_path'].startswith('rehab/starting_posture/recordings/')
 assert (vault.module_manifest('starting_posture')).is_file()

def test_module_manifests_are_physically_separate(tmp_path):
 vault=DatasetVault(config(tmp_path));vault.generate_manifests()
 for module in vault.registry.modules:
  base=vault.module_path(module.slug)
  assert (base/'module_metadata.json').is_file()
  assert (base/'manifests/dataset_manifest.csv').is_file()
  metadata=json.loads((base/'module_metadata.json').read_text(encoding='utf-8'))
  assert metadata['rehab_type']==module.id

def test_recording_configuration_requires_rehab_type():
 from backend.dataset_models import RecordingConfiguration
 import pytest
 with pytest.raises(Exception): RecordingConfiguration(subject_id='P1',category='STARTING_POSTURE',label='acceptable_start',duration_seconds=3,consent_recorded=True)
 model=RecordingConfiguration(rehab_type='STARTING_POSTURE',subject_id='P1',category='STARTING_POSTURE',label='acceptable_start',duration_seconds=3,consent_recorded=True)
 assert model.rehab_type=='STARTING_POSTURE'

def test_registry_rejects_unsafe_and_duplicate_slugs(tmp_path):
 import pytest
 bad=tmp_path/'bad.json';bad.write_text('{"modules":[{"id":"A","slug":"../bad","display_name":"A","description":"x","labels":[{"id":"x"}]}]}',encoding='utf-8')
 with pytest.raises(ValueError): RehabModuleRegistry(bad)

def test_archived_module_is_readable_but_cannot_collect(tmp_path):
 import pytest
 path=tmp_path/'modules.json';path.write_text('{"modules":[{"id":"ARCHIVED","slug":"archived","display_name":"Archived","description":"x","enabled":false,"labels":[{"id":"old","display_name":"Old"}]}]}',encoding='utf-8')
 registry=RehabModuleRegistry(path);assert registry.by_slug('archived').enabled is False
 with pytest.raises(ValueError):registry.validate_label('ARCHIVED','old')
 assert registry.validate_label('ARCHIVED','old',require_enabled=False).id=='ARCHIVED'

def test_schema_v3_metadata_and_global_manifest_fields_exist():
 source=__import__('pathlib').Path('backend/cv_recording_service.py').read_text(encoding='utf-8')
 assert 'rehab_type' in source and 'rehab_slug' in source and 'dataset_schema_version' in source
 fields=__import__('pathlib').Path('backend/dataset_vault.py').read_text(encoding='utf-8')
 assert "'rehab_type','rehab_slug'" in fields