"""Build bounded, secret-free source/data/release archives and recompute hashes."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import zipfile

FORBIDDEN={'.git','.superpowers','node_modules','__pycache__','.pytest_cache','id_rsa','id_ed25519','credentials.json'}
ARTIFACTS=('project-report.pdf','engineering-report.pdf','project-report.md','engineering-report.md','demo.mp4','demo.srt','demo-capture.json','demo-script.md','evidence.html','DELIVERY.md','architecture.md','manual-review.md','assessment-matrix.md','ai-collaboration-log.csv','frontend-main.png','frontend-mobile.png','frontend-mvt.png','final-atlas.png','map-module.zip','design-tokens.json','module-guide.md')
def hash_file(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def safe_member(name):
 if not isinstance(name,str) or not name or '\\' in name or ':' in name or '\x00' in name:raise ValueError('Unsafe artifact member')
 name=name[:-1] if name.endswith('/') else name
 p=PurePosixPath(name)
 if p.is_absolute() or p.as_posix()!=name or any(x in ('','.','..') or x!=x.rstrip(' .') for x in p.parts):raise ValueError('Unsafe artifact member')
 for x in p.parts:
  lower=x.casefold()
  if lower in FORBIDDEN or (lower.startswith('.env') and lower!='.env.example'):raise ValueError('Secret/runtime artifact member')
 return name
def inspect_zip(path,source=False):
 seen=set();total=0
 with zipfile.ZipFile(path) as archive:
  for info in archive.infolist():
   name=safe_member(info.filename);key=name.casefold()
   if key in seen:raise ValueError('Duplicate archive member')
   seen.add(key)
   if stat.S_ISLNK(info.external_attr>>16):raise ValueError('Archive links forbidden')
   if source and re.match(r'^data/(raw|processed)/',name) and not info.is_dir() and not name.endswith('/.gitkeep'):raise ValueError('Source includes runtime data')
   total+=info.file_size
   if total>256*1024*1024:raise ValueError('Archive exceeds bounded delivery size')
  if archive.testzip() is not None:raise ValueError('Corrupt archive')
 return {'members':len(seen),'uncompressed_bytes':total}
def _write(archive,name,data):
 info=zipfile.ZipInfo(safe_member(name),(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(stat.S_IFREG|0o644)<<16
 archive.writestr(info,data)
def data_archive(dataset,output):
 dataset=Path(dataset).resolve();output=Path(output)
 if output.exists():raise FileExistsError('Archive exists')
 if dataset.is_symlink():raise ValueError('Linked data root')
 manifest=json.loads((dataset/'manifest.json').read_text(encoding='utf-8-sig'))
 generation=manifest['generation_id']
 if not re.fullmatch('[0-9a-f]{20}',generation) or dataset.name!=generation:raise ValueError('Invalid generation')
 entries=[]
 for name,digest in manifest['files'].items():
  relative=safe_member(name);path=dataset/relative
  if not path.resolve().is_relative_to(dataset) or path.is_symlink() or hash_file(path)!=digest:raise ValueError('Invalid data manifest hash/path')
  entries.append((relative,path))
 with zipfile.ZipFile(output,'x') as archive:
  for name,path in sorted(entries):_write(archive,f'teaching-v1/{generation}/{name}',path.read_bytes())
  _write(archive,f'teaching-v1/{generation}/manifest.json',(dataset/'manifest.json').read_bytes())
  _write(archive,'teaching-v1/latest.json',json.dumps({'generation_id':generation,'relative_path':generation}).encode())
 return inspect_zip(output)
def source_archive(repo,commit,output):
 repo=Path(repo);output=Path(output)
 if output.exists():raise FileExistsError('Source archive exists')
 resolved=subprocess.check_output(['git','-C',str(repo),'rev-parse','--verify',commit+'^{commit}'],text=True).strip()
 if not re.fullmatch('[0-9a-f]{40}',resolved):raise ValueError('Invalid source commit')
 subprocess.run(['git','-C',str(repo),'archive','--format=zip','--output='+str(output.resolve()),resolved],check=True,capture_output=True)
 inspect_zip(output,source=True)
 return resolved
def verify_release(root):
 root=Path(root)
 manifest=json.loads((root/'release-manifest.json').read_text(encoding='utf-8-sig'))
 if not re.fullmatch('[0-9a-f]{40}',manifest.get('source_commit','')) or not re.fullmatch('[0-9a-f]{20}',manifest.get('dataset_generation','')):raise ValueError('Missing release provenance')
 expected={'release-manifest.json','SHA256SUMS.txt'}
 rows=manifest['files']
 if {r['name'] for r in rows}!=set(ARTIFACTS)|{'source.zip','teaching-data.zip'}:raise ValueError('Incomplete delivery artifacts')
 for row in rows:
  name=safe_member(row['name'])
  if '/' in name or name in expected:raise ValueError('Duplicate or nested release member')
  expected.add(name);path=root/name
  if path.is_symlink() or not path.is_file() or path.stat().st_size!=row['bytes'] or hash_file(path)!=row['sha256']:raise ValueError('Release hash mismatch')
  if name.endswith('.zip'):inspect_zip(path,source=name=='source.zip')
 if {p.name for p in root.iterdir()}!=expected:raise ValueError('Unexpected release member')
 sums={}
 for line in (root/'SHA256SUMS.txt').read_text().splitlines():
  digest,name=line.split('  ',1);safe_member(name)
  if name in sums or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Invalid checksum list')
  sums[name]=digest
 if set(sums)!=expected-{'SHA256SUMS.txt'}:raise ValueError('Incomplete checksum list')
 for name,digest in sums.items():
  if hash_file(root/name)!=digest:raise ValueError('Checksum file mismatch')
 return {'status':'ok','files':len(expected)}
def _no_secrets(repo,root):
 path=Path(repo)/'.env'
 if not path.exists():return
 secrets=[]
 for line in path.read_text(encoding='utf-8-sig').splitlines():
  if re.match(r'^(POSTGRES_PASSWORD|GEOSERVER_ADMIN_PASSWORD)=',line):
   value=line.split('=',1)[1].strip().strip('"\'')
   if value and value!='CHANGE_ME':secrets.append(value.encode())
 for file in Path(root).iterdir():
  contents=[]
  if file.suffix=='.zip':
   with zipfile.ZipFile(file) as z:contents=[z.read(i) for i in z.infolist() if not i.is_dir()]
  else:contents=[file.read_bytes()]
  if any(secret in content for secret in secrets for content in contents):raise ValueError('Local secret detected; value omitted')
def build_release(repo,dataset,artifacts,output,commit='HEAD'):
 repo=Path(repo);artifacts=Path(artifacts);output=Path(output)
 if output.exists() or output.with_suffix('.zip').exists():raise FileExistsError('Release output exists')
 for name in ARTIFACTS:
  if not (artifacts/name).is_file() or (artifacts/name).is_symlink():raise ValueError('Required delivery artifact missing')
 output.mkdir(parents=True)
 resolved=source_archive(repo,commit,output/'source.zip');data_archive(dataset,output/'teaching-data.zip')
 for name in ARTIFACTS:shutil.copyfile(artifacts/name,output/name)
 rows=[{'name':p.name,'bytes':p.stat().st_size,'sha256':hash_file(p)} for p in sorted(output.iterdir())]
 manifest={'source_commit':resolved,'dataset_generation':Path(dataset).name,'files':rows,'privacy':'No .env or runtime credentials; local secret value scan passed.'}
 (output/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 (output/'SHA256SUMS.txt').write_text(''.join(f'{hash_file(p)}  {p.name}\n' for p in sorted(output.iterdir())),encoding='utf-8')
 _no_secrets(repo,output);result=verify_release(output)
 outer=output.with_suffix('.zip')
 with zipfile.ZipFile(outer,'x') as archive:
  for p in sorted(output.iterdir()):_write(archive,p.name,p.read_bytes())
 inspect_zip(outer)
 result.update(source_commit=resolved,archive=str(outer.resolve()),archive_sha256=hash_file(outer))
 outer.with_suffix('.zip.sha256').write_text(f'{result["archive_sha256"]}  {outer.name}\n',encoding='utf-8')
 return result
def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['build','verify','core']);p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--dataset',type=Path);p.add_argument('--artifacts',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--commit',default='HEAD');a=p.parse_args()
 if a.command=='verify':result=verify_release(a.output)
 elif a.command=='build':result=build_release(a.repo,a.dataset,a.artifacts,a.output,a.commit)
 else:
  a.output.mkdir(parents=True,exist_ok=False);commit=source_archive(a.repo,a.commit,a.output/'source.zip');data=data_archive(a.dataset,a.output/'teaching-data.zip');_no_secrets(a.repo,a.output);result={'status':'ok','source_commit':commit,'data':data}
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
