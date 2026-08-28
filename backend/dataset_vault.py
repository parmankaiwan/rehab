from __future__ import annotations
import csv,json,shutil,sqlite3
from types import SimpleNamespace
from datetime import datetime,timezone
from pathlib import Path
from threading import RLock
from typing import Optional
from .dataset_config import DatasetSettings
from .dataset_quality import validate_sample_integrity
from .rehab_modules import RehabModuleRegistry
class DatasetVault:
 def __init__(self,settings:DatasetSettings)->None:
  self.settings=settings;self.registry=RehabModuleRegistry(settings.modules_path);self._lock=RLock()
  for path in (settings.root,settings.temp_dir,settings.recordings_dir,settings.rehab_dir,settings.global_manifests_dir):path.mkdir(parents=True,exist_ok=True)
  self._initialize();self._initialize_modules();self.recovery=self.scan_temp_recovery()
 def _connect(self):db=sqlite3.connect(self.settings.database_path,timeout=10);db.row_factory=sqlite3.Row;return db
 def _initialize(self):
  with self._connect() as db:
   db.executescript('''CREATE TABLE IF NOT EXISTS recording_sequence(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS session_sequence(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS recordings(recording_id TEXT PRIMARY KEY,subject_id TEXT NOT NULL,session_id TEXT,category TEXT NOT NULL,label TEXT NOT NULL,original_label TEXT NOT NULL,affected_side TEXT,view TEXT,created_at TEXT NOT NULL,duration_seconds REAL NOT NULL,frame_count INTEGER NOT NULL,pose_result_count INTEGER NOT NULL,tracking_good_ratio REAL NOT NULL,tracking_poor_ratio REAL NOT NULL,tracking_lost_ratio REAL NOT NULL,review_status TEXT NOT NULL,approved INTEGER NOT NULL,relative_path TEXT NOT NULL,notes TEXT NOT NULL,label_updated_at TEXT,deleted_at TEXT);CREATE TABLE IF NOT EXISTS label_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,recording_id TEXT NOT NULL,old_category TEXT NOT NULL,old_label TEXT NOT NULL,new_category TEXT NOT NULL,new_label TEXT NOT NULL,changed_at TEXT NOT NULL);CREATE TABLE IF NOT EXISTS dataset_audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,recording_id TEXT,action TEXT NOT NULL,previous_value TEXT,new_value TEXT);''')
   existing={row[1] for row in db.execute('PRAGMA table_info(recordings)')};columns={"technical_quality":"TEXT","training_eligible":"INTEGER NOT NULL DEFAULT 0","excluded":"INTEGER NOT NULL DEFAULT 0","exclusion_reason":"TEXT","excluded_at":"TEXT","dataset_schema_version":"TEXT NOT NULL DEFAULT '1.0'","protocol_id":"TEXT","trial_number":"INTEGER NOT NULL DEFAULT 1","sample_size_bytes":"INTEGER NOT NULL DEFAULT 0","rehab_type":"TEXT NOT NULL DEFAULT 'UNASSIGNED'","rehab_slug":"TEXT NOT NULL DEFAULT 'unassigned'"}
   for name,definition in columns.items():
    if name not in existing:db.execute(f'ALTER TABLE recordings ADD COLUMN {name} {definition}')
   for sql in ('CREATE INDEX IF NOT EXISTS idx_recordings_session ON recordings(session_id)','CREATE INDEX IF NOT EXISTS idx_recordings_rehab ON recordings(rehab_type)','CREATE INDEX IF NOT EXISTS idx_recordings_rehab_label ON recordings(rehab_type,label)','CREATE INDEX IF NOT EXISTS idx_recordings_rehab_subject ON recordings(rehab_type,subject_id)','CREATE INDEX IF NOT EXISTS idx_recordings_rehab_eligible ON recordings(rehab_type,training_eligible)'):db.execute(sql)
 def _initialize_modules(self):
  for module in self.registry.modules:
   base=self.module_path(module.slug);(base/'recordings').mkdir(parents=True,exist_ok=True);(base/'manifests').mkdir(exist_ok=True);(base/'module_metadata.json').write_text(json.dumps({"rehab_type":module.id,"rehab_slug":module.slug,"display_name":module.name,"module_schema_version":"1.0","description":module.description,"enabled":module.enabled,"model_scope":module.id},indent=2),encoding='utf-8')
 def module_path(self,slug):
  module=self.registry.by_slug(slug);path=(self.settings.rehab_dir/module.slug).resolve()
  if path.parent!=self.settings.rehab_dir.resolve():raise ValueError('Unsafe rehab path')
  return path
 def _audit(self,db,rid,action,previous=None,new=None):db.execute('INSERT INTO dataset_audit_log(timestamp,recording_id,action,previous_value,new_value) VALUES(?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),rid,action,json.dumps(previous) if previous is not None else None,json.dumps(new) if new is not None else None))
 def new_recording_id(self):
  now=datetime.now(timezone.utc)
  with self._lock,self._connect() as db:number=db.execute('INSERT INTO recording_sequence(created_at) VALUES(?)',(now.isoformat(),)).lastrowid
  return f'REC-{now:%Y%m%d}-{number:06d}'
 def next_session_id(self):
  now=datetime.now(timezone.utc)
  with self._connect() as db:number=db.execute('INSERT INTO session_sequence(created_at) VALUES(?)',(now.isoformat(),)).lastrowid
  return f'SESSION-{now:%Y%m%d}-{number:03d}'
 def next_trial(self,subject,session,category,label):
  with self._connect() as db:row=db.execute('SELECT MAX(trial_number) FROM recordings WHERE subject_id=? AND session_id=? AND category=? AND label=?',(subject,session,category,label)).fetchone()
  return int(row[0] or 0)+1
 def temp_path(self,rid):
  path=(self.settings.temp_dir/rid).resolve()
  if path.parent!=self.settings.temp_dir.resolve() or not rid.startswith('REC-'):raise ValueError('Invalid recording ID')
  return path
 def recording_path(self,rid,slug=None):
  base=(self.module_path(slug)/'recordings') if slug else self.settings.recordings_dir;path=(base/rid).resolve()
  if path.parent!=base.resolve() or not rid.startswith('REC-'):raise ValueError('Invalid recording ID')
  return path
 def scan_temp_recovery(self):return [{"recording_id":p.name,"status":"RECOVERY_NEEDED"} for p in self.settings.temp_dir.iterdir() if p.is_dir()]
 def save_temp(self,rid):
  source=self.temp_path(rid)
  if not source.is_dir():raise FileNotFoundError('Recording unavailable')
  metadata=json.loads((source/'metadata.json').read_text(encoding='utf-8'));legacy='rehab_type' not in metadata;module=SimpleNamespace(id='UNASSIGNED',slug='unassigned') if legacy else self.registry.validate_label(metadata['rehab_type'],metadata['label']);metadata['rehab_type']=module.id;metadata['rehab_slug']=module.slug;metadata['dataset_schema_version']='1.0' if legacy else '3.0';target=self.recording_path(rid,None if legacy else module.slug)
  if target.exists():raise FileExistsError('Duplicate recording path')
  errors=[] if legacy else validate_sample_integrity(source,metadata);quality=metadata.get('technical_quality','USABLE_WITH_WARNINGS')
  if errors or quality=='INVALID':raise ValueError('SAMPLE INTEGRITY ERROR: '+', '.join(errors or ['INVALID']))
  status='APPROVED' if quality=='GOOD' else 'APPROVED_WITH_WARNINGS';eligible=status=='APPROVED';metadata.update(approved=True,review_status=status,training_eligible=eligible);(source/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8');shutil.move(str(source),str(target));relative=str(target.relative_to(self.settings.root)).replace('\\','/');size=sum(p.stat().st_size for p in target.rglob('*') if p.is_file())
  with self._connect() as db:
   fields=('recording_id,subject_id,session_id,category,label,original_label,affected_side,view,created_at,duration_seconds,frame_count,pose_result_count,tracking_good_ratio,tracking_poor_ratio,tracking_lost_ratio,review_status,approved,relative_path,notes,label_updated_at,deleted_at,technical_quality,training_eligible,excluded,exclusion_reason,excluded_at,dataset_schema_version,protocol_id,trial_number,sample_size_bytes,rehab_type,rehab_slug')
   values=(rid,metadata['subject_id'],metadata.get('session_id'),module.id,metadata['label'],metadata['label'],metadata.get('affected_side'),metadata.get('view'),metadata['created_at'],metadata['duration_actual_seconds'],metadata['frame_count'],metadata['pose_result_count'],metadata['tracking_good_ratio'],metadata['tracking_poor_ratio'],metadata['tracking_lost_ratio'],status,1,relative,metadata.get('notes',''),None,None,quality,int(eligible),0,None,None,metadata['dataset_schema_version'],metadata.get('protocol_id'),metadata.get('trial_number',1),size,module.id,module.slug)
   db.execute(f'INSERT INTO recordings({fields}) VALUES({",".join("?" for _ in values)})',values);self._audit(db,rid,'SAMPLE_APPROVED',None,{"rehab_type":module.id,"status":status})
  self.generate_manifests();return metadata
 def discard_temp(self,rid):
  path=self.temp_path(rid)
  if path.exists():shutil.rmtree(path)
 def list(self,*,search='',subject='',category='',label='',affected_side='',tracking='',status='',session_id='',rehab_type=''):
  clauses=['deleted_at IS NULL'];values=[]
  for column,value in (("subject_id",subject),("category",category),("label",label),("affected_side",affected_side),("review_status",status),("session_id",session_id),("rehab_type",rehab_type)):
   if value:clauses.append(f'{column}=?');values.append(value)
  if search:clauses.append('(recording_id LIKE ? OR subject_id LIKE ? OR session_id LIKE ?)');values.extend([f'%{search}%']*3)
  if tracking=='GOOD':clauses.append('tracking_good_ratio>=.8')
  elif tracking=='POOR':clauses.append('tracking_good_ratio<.8 AND tracking_lost_ratio<.5')
  elif tracking=='LOST':clauses.append('tracking_lost_ratio>=.5')
  with self._connect() as db:rows=db.execute('SELECT * FROM recordings WHERE '+' AND '.join(clauses)+' ORDER BY created_at DESC',values).fetchall()
  return [dict(row) for row in rows]
 def get(self,rid)->Optional[dict]:
  with self._connect() as db:row=db.execute('SELECT * FROM recordings WHERE recording_id=? AND deleted_at IS NULL',(rid,)).fetchone()
  if not row:return None
  item=dict(row);path=(self.settings.root/item['relative_path']).resolve()
  if not path.is_relative_to(self.settings.root.resolve()) or not path.is_dir():return None
  item['metadata']=json.loads((path/'metadata.json').read_text(encoding='utf-8'));item['quality_report']=json.loads((path/'quality_report.json').read_text(encoding='utf-8')) if (path/'quality_report.json').is_file() else None;item['files']=sorted(p.name for p in path.iterdir() if p.is_file());item['legacy_sample']=item.get('dataset_schema_version','1.0') in ('1.0','2.0');return item
 def update(self,rid,*,category=None,label=None,notes=None):
  current=self.get(rid)
  if not current:raise FileNotFoundError(rid)
  new_label=label or current['label'];module=self.registry.by_id(current['rehab_type']) if current['rehab_type']!='UNASSIGNED' else None
  if module and new_label not in module.labels:raise ValueError('Label does not belong to sample rehab type')
  now=datetime.now(timezone.utc).isoformat()
  with self._connect() as db:
   if new_label!=current['label']:db.execute('INSERT INTO label_audit(recording_id,old_category,old_label,new_category,new_label,changed_at) VALUES(?,?,?,?,?,?)',(rid,current['category'],current['label'],current['category'],new_label,now));self._audit(db,rid,'SAMPLE_RELABELED',current['label'],new_label)
   db.execute('UPDATE recordings SET label=?,notes=?,label_updated_at=? WHERE recording_id=?',(new_label,notes if notes is not None else current['notes'],now,rid))
  path=self.settings.root/current['relative_path']/'metadata.json';metadata=json.loads(path.read_text(encoding='utf-8'));metadata.update(label=new_label,research_label=new_label,notes=notes if notes is not None else current['notes'],label_updated_at=now,original_label=current['original_label']);path.write_text(json.dumps(metadata,indent=2),encoding='utf-8');self.generate_manifests();return self.get(rid)
 def assign_rehab(self,rid,rehab_type,label,confirm):
  if not confirm:raise ValueError('Rehab type change requires confirmation')
  current=self.get(rid)
  if not current:raise FileNotFoundError(rid)
  module=self.registry.validate_label(rehab_type,label);old_type=current['rehab_type'];old_path=(self.settings.root/current['relative_path']).resolve();new_path=self.recording_path(rid,module.slug)
  if new_path.exists():raise FileExistsError('Destination recording already exists')
  new_path.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(old_path),str(new_path));relative=str(new_path.relative_to(self.settings.root)).replace('\\','/')
  try:
   meta_path=new_path/'metadata.json';metadata=json.loads(meta_path.read_text(encoding='utf-8'));metadata.update(rehab_type=module.id,rehab_slug=module.slug,label=label,research_label=label,training_eligible=False,review_status='REVIEW');meta_path.write_text(json.dumps(metadata,indent=2),encoding='utf-8')
   with self._connect() as db:db.execute("UPDATE recordings SET rehab_type=?,rehab_slug=?,category=?,label=?,relative_path=?,training_eligible=0,review_status='REVIEW' WHERE recording_id=?",(module.id,module.slug,module.id,label,relative,rid));self._audit(db,rid,'REHAB_TYPE_ASSIGNED' if old_type=='UNASSIGNED' else 'REHAB_TYPE_CHANGED',{"rehab_type":old_type},{"rehab_type":module.id,"label":label});self._audit(db,rid,'REHAB_SAMPLE_MOVED',current['relative_path'],relative)
  except Exception:
   shutil.move(str(new_path),str(old_path));raise
  self.generate_manifests();return self.get(rid)
 def set_excluded(self,rid,excluded,reason=None):
  current=self.get(rid)
  if not current:raise FileNotFoundError(rid)
  now=datetime.now(timezone.utc).isoformat();eligible=int(not excluded and current['review_status']=='APPROVED')
  with self._connect() as db:db.execute('UPDATE recordings SET excluded=?,exclusion_reason=?,excluded_at=?,training_eligible=?,review_status=? WHERE recording_id=?',(int(excluded),reason if excluded else None,now if excluded else None,eligible,'EXCLUDED' if excluded else ('APPROVED' if current['approved'] else current['review_status']),rid));self._audit(db,rid,'SAMPLE_EXCLUDED' if excluded else 'SAMPLE_RESTORED',None,{"excluded":excluded,"reason":reason})
  self.generate_manifests();return self.get(rid)
 def delete(self,rid):
  current=self.get(rid)
  if not current:raise FileNotFoundError(rid)
  path=(self.settings.root/current['relative_path']).resolve()
  if not path.is_relative_to(self.settings.root.resolve()):raise ValueError('Unsafe dataset path')
  with self._connect() as db:self._audit(db,rid,'SAMPLE_DELETED');db.execute("UPDATE recordings SET deleted_at=?,approved=0,training_eligible=0,review_status='DELETED' WHERE recording_id=?",(datetime.now(timezone.utc).isoformat(),rid))
  shutil.rmtree(path);self.generate_manifests()
 def stats(self,rehab_type=''):
  rows=self.list(rehab_type=rehab_type);labels={};subjects={};sides={};quality={}
  for row in rows:
   for bucket,key in ((labels,row['label']),(subjects,row['subject_id']),(sides,row.get('affected_side') or 'UNKNOWN'),(quality,row.get('technical_quality') or 'LEGACY')):bucket[key]=bucket.get(key,0)+1
  return {"total_samples":len(rows),"approved":sum(bool(r['approved']) for r in rows),"training_eligible":sum(bool(r['training_eligible']) for r in rows),"excluded":sum(bool(r['excluded']) for r in rows),"invalid":sum(r['review_status']=='INVALID' for r in rows),"approved_with_warnings":sum(r['review_status']=='APPROVED_WITH_WARNINGS' for r in rows),"total_duration_seconds":sum(r['duration_seconds'] for r in rows),"unique_subjects":len(subjects),"label_counts":labels,"subject_counts":subjects,"side_counts":sides,"quality_counts":quality,"storage_bytes":sum(r.get('sample_size_bytes',0) for r in rows),"free_storage_bytes":shutil.disk_usage(self.settings.root).free,"rehab_type":rehab_type or 'GLOBAL'}
 def module_summaries(self):
  result=[]
  for module in self.registry.modules:result.append({**module.as_dict(),"stats":self.stats(module.id)})
  result.append({"id":"UNASSIGNED","slug":"unassigned","name":"Unassigned Recordings","description":"Legacy samples awaiting manual assignment.","enabled":False,"labels":[],"stats":self.stats('UNASSIGNED')});return result
 def generate_manifests(self):
  fields=['recording_id','rehab_type','rehab_slug','subject_id','session_id','label','original_label','affected_side','created_at','duration_seconds','technical_quality','review_status','training_eligible','excluded','dataset_schema_version','relative_path']
  self.settings.global_manifests_dir.mkdir(exist_ok=True);targets=[(self.settings.global_manifests_dir/'global_dataset_manifest.csv',self.list(),False)]
  for module in self.registry.modules:
   base=self.module_path(module.slug)/'manifests';rows=self.list(rehab_type=module.id);targets.extend([(base/'dataset_manifest.csv',rows,False),(base/'training_manifest.csv',rows,True)])
  for path,rows,training_only in targets:
   with path.open('w',newline='',encoding='utf-8') as handle:
    writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
    for row in rows:
     if training_only and not row['training_eligible']:continue
     writer.writerow({key:row.get(key) for key in fields})
  shutil.copy2(self.settings.global_manifests_dir/'global_dataset_manifest.csv',self.settings.manifest_path)
  with self.settings.training_manifest_path.open('w',newline='',encoding='utf-8') as handle:csv.DictWriter(handle,fieldnames=fields).writeheader()
  return self.settings.manifest_path
 def module_manifest(self,slug,training=False):
  module=self.registry.by_slug(slug);self.generate_manifests();return self.module_path(module.slug)/'manifests'/('training_manifest.csv' if training else 'dataset_manifest.csv')
 def generate_manifest(self):return self.generate_manifests()