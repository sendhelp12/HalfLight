import hashlib,json
from pathlib import Path
r=Path(__file__).resolve().parents[1];results=json.loads((r/'work/lab/catalog-capture-results.json').read_text());items=json.loads((r/'work/owned-assets/catalog/selections.json').read_text());assets={};assemblies=[]
assert len(items)==len(results),'Incomplete local capture batch'
for item,result in zip(items,results):
 assert result['id']==item['id'] and result['state']=='captured',result
 lines=(r/f'work/lab/catalog-capture-{result["nonce"]}.txt').read_text().splitlines();kv=dict(l.split('=',1) for l in lines if '=' in l and not l.startswith(('part=','grip=','property=')))
 root=[float(x) for x in kv['root_transform'].split(',')];assert max(map(abs,root[:3]))<1e6
 parts=[]
 for line in lines:
  if not line.startswith('part='):continue
  fs=line.split('|');name=fs[0].split('.')[-1];asset=fs[1].split('=',1)[1].removeprefix('StaticMesh ');t=[float(x) for x in fs[3].split('=',1)[1].split(',')]
  if 'SM_Grip_Dummy' in asset or max(map(abs,t[:3]))>1e6:continue
  output=r/'work/owned-assets/catalog/meshes'/(hashlib.sha256(asset.encode()).hexdigest()[:16]+'.json');assets[asset]=str(output)
  parts.append({'name':name,'asset':asset,'transform':t,'geometry':str(output.relative_to(r)).replace('\\','/')})
 component=kv['root'].split('.')[-1]
 if component not in {p['name'] for p in parts}:
  pivot=next((p for key in ('Blade','Weapon','Blade1','Grip_0') for p in parts if p['name']==key),parts[0]);component=pivot['name'];root=pivot['transform']
 item.update(actor_class=kv['actor'].split(' ')[0],component=component,root_transform=root,parts=parts,capture=result['nonce'])
 assemblies.append(item)
(r/'work/owned-assets/catalog/meshes').mkdir(exist_ok=True)
(r/'work/owned-assets/catalog/assemblies.json').write_text(json.dumps(assemblies,indent=2))
(r/'work/lab/catalog-mesh-requests.json').write_text(json.dumps([{'source':a,'output':p} for a,p in assets.items()],indent=2));print(len(assemblies),'assemblies',len(assets),'meshes')
