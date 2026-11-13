import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
from tools.delivery.bundle import ARTIFACTS, safe_member, inspect_zip, data_archive, hash_file, verify_release

class BundleTests(unittest.TestCase):
 def test_secrets_runtime_paths_and_traversal_rejected(self):
  self.assertEqual(safe_member('.env.example'),'.env.example')
  for name in ['../escape','/absolute','C:/x','a\\b','a//b','.ENV','nested/.env.local','node_modules/x','.git/config','.superpowers/ledger','secrets/id_rsa']:
   with self.subTest(name=name),self.assertRaises(ValueError):safe_member(name)
 def test_archive_link_and_source_runtime_are_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'bad.zip'
   with zipfile.ZipFile(path,'w') as z:
    item=zipfile.ZipInfo('docs/link');item.create_system=3;item.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(item,'../../secret')
   with self.assertRaises(ValueError):inspect_zip(path)
   with zipfile.ZipFile(path,'w') as z:z.writestr('data/processed/live.tif',b'x')
   with self.assertRaises(ValueError):inspect_zip(path,source=True)
 def test_data_archive_requires_every_hash_and_refuses_overwrite(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);dataset=root/'0123456789abcdef0123';dataset.mkdir();(dataset/'import.json').write_bytes(b'{}')
   manifest={'generation_id':dataset.name,'files':{'import.json':hash_file(dataset/'import.json')}}
   (dataset/'manifest.json').write_text(json.dumps(manifest))
   archive=root/'data.zip';data_archive(dataset,archive)
   with zipfile.ZipFile(archive) as z:self.assertIn('teaching-v1/latest.json',z.namelist())
   with self.assertRaises(FileExistsError):data_archive(dataset,archive)
   (dataset/'import.json').write_bytes(b'corrupt')
   with self.assertRaises(ValueError):data_archive(dataset,root/'bad.zip')
 def test_release_verification_recomputes_hashes_and_rejects_extra_or_tampered_files(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);file=root/'report.pdf';file.write_bytes(b'actual')
   file.unlink()
   for name in ARTIFACTS:(root/name).write_bytes(b'actual')
   for name in ['source.zip','teaching-data.zip']+[v for v in ARTIFACTS if v.endswith('.zip')]:
    with zipfile.ZipFile(root/name,'w') as z:z.writestr('README.md','fixture')
   file=root/'project-report.pdf'
   files=[{'name':p.name,'sha256':hash_file(p),'bytes':p.stat().st_size} for p in root.iterdir()]
   (root/'release-manifest.json').write_text(json.dumps({'source_commit':'a'*40,'dataset_generation':'0123456789abcdef0123','files':files}))
   (root/'SHA256SUMS.txt').write_text(''.join(f'{hash_file(p)}  {p.name}\n' for p in root.iterdir()))
   self.assertEqual(verify_release(root)['status'],'ok')
   file.write_bytes(b'wrong')
   with self.assertRaises(ValueError):verify_release(root)
   file.write_bytes(b'actual');(root/'extra.env').write_text('unexpected')
   with self.assertRaises(ValueError):verify_release(root)
 def test_self_consistent_but_incomplete_release_is_not_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   (root/'release-manifest.json').write_text(json.dumps({'source_commit':'a'*40,'dataset_generation':'0123456789abcdef0123','files':[]}))
   (root/'SHA256SUMS.txt').write_text(f"{hash_file(root/'release-manifest.json')}  release-manifest.json\n")
   with self.assertRaises(ValueError):verify_release(root)

if __name__=='__main__':unittest.main()
