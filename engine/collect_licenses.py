"""Collect resolved dependency license texts without publishing runner paths."""
import json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
meta=json.loads(subprocess.check_output(['cargo','metadata','--locked','--format-version','1'],cwd=root))
chunks=[];inventory=[]
for package in sorted(meta['packages'],key=lambda p:(p['name'],p['version'])):
 base=Path(package['manifest_path']).parent;files=[]
 for folder in (base,base.parent):
  files.extend(p for p in folder.iterdir() if p.is_file() and p.name.upper().startswith(('LICENSE','LICENCE','COPYING','NOTICE')))
 explicit=package.get('license_file')
 if explicit and (base/explicit).is_file():files.append(base/explicit)
 unique=sorted(set(files));label=package['name']+' '+package['version'];license_id=package.get('license')
 chunks.append('\n===== '+label+' | '+str(license_id)+' =====\n')
 for p in unique:chunks.append('\n--- '+p.name+' ---\n'+p.read_text('utf8',errors='replace')+'\n')
 inventory.append({'name':package['name'],'version':package['version'],'license':license_id,'repository':package.get('repository'),'license_files':[p.name for p in unique]})
out=root/'target/license-report';out.mkdir(parents=True,exist_ok=True)
(out/'THIRD_PARTY_LICENSES.txt').write_text(''.join(chunks),'utf8',newline='\n')
(out/'dependency-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n','utf8',newline='\n')
print('Collected license records for',len(inventory),'resolved packages; no credentials or game assets used')
