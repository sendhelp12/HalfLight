"""Bake observed assemblies into their live component frame; official exporter."""
import json, math, runpy, sys
from pathlib import Path
from mathutils import Matrix, Quaternion, Vector
ROOT=Path(__file__).resolve().parents[1]

def matrix(t):
    q=Quaternion((t[6],*t[3:6]))
    return Matrix.Translation(Vector(t[:3]))@q.to_matrix().to_4x4()@Matrix.Diagonal(Vector((*t[7:],1)))

profiles=[]
for item in json.loads((ROOT/'work/owned-assets/catalog/assemblies.json').read_text()):
    data={'format':'HalfLightStaticMesh1','source':'owned-equipped-'+item['id'],'vertices':[],'normals':[],'uvs':[],'indices':[],'sections':[],'material_indices':{}}
    inverse=matrix(item['root_transform'][:7]+[1,1,1]).inverted(); head=[]
    for part in item['parts']:
        source=json.loads((ROOT/part['geometry']).read_text()); transform=inverse@matrix(part['transform']);normal=transform.to_3x3().inverted().transposed()
        vertices=[list(transform@Vector(v)) for v in source['vertices']];offset=len(data['vertices']);first=len(data['indices'])
        data['vertices'].extend(vertices);data['normals'].extend(list((normal@Vector(n)).normalized()) for n in source['normals']);data['uvs'].extend(source['uvs']);data['indices'].extend(i+offset for i in source['indices'])
        for section in source['sections']:data['sections'].append(dict(section,FirstIndex=first+section['FirstIndex'],part=part['name']))
        shaft=part['name'] in ('Grip','Grip_0')
        data['material_indices'][part['name']]=1 if shaft and item['family']=='Swords' else 2 if shaft else 0
        if not shaft:head.extend(vertices)
    if not head:head=data['vertices']
    folder=ROOT/'work/owned-assets/catalog'/item['id'];folder.mkdir(exist_ok=True);source=folder/'geometry.json';source.write_text(json.dumps(data))
    # shortcut: one capsule around each striking part's bounds, matching the
    # existing sword route; use multiple edge segments if balance needs them.
    lo=[min(v[a] for v in head)*.01 for a in range(3)];hi=[max(v[a] for v in head)*.01 for a in range(3)];axis=max(range(3),key=lambda a:hi[a]-lo[a]);centre=[(a+b)/2 for a,b in zip(lo,hi)]
    ends=[centre.copy(),centre.copy()];ends[0][axis]=lo[axis];ends[1][axis]=hi[axis]
    radius=min(.095,max(.008,math.sqrt(sum(((hi[a]-lo[a])/2)**2 for a in range(3) if a!=axis))))
    profile={k:item[k] for k in ('id','label','family','actor_class','component','damage_type','source_class_path')}
    if item.get('recipe'):profile['recipe']=item['recipe']
    profile.update(native_mesh=item['native_mesh'],pose_offset_cm=0,source_scale=item['root_transform'][7:],source_parts={p['name']:p['asset'] for p in item['parts']},source_part_scales={p['name']:p['transform'][7:] for p in item['parts']},cutting_segment_m=[[v[0],v[2],v[1]] for v in ends],blade_radius_m=radius,grip_centre_m=[0,0,0],grip_radius_m=.015,geometry_path=str(source.relative_to(ROOT)).replace('\\','/'),geometry_offset_cm=0,grip_shape='cylinder')
    profiles.append(profile)
    sys.argv=['Convert-Guest-Sword.py','--',profile['geometry_path'],Path(profile['native_mesh']).stem]
    runpy.run_path(str(ROOT/'outputs/HalfLightNext/Convert-Guest-Sword.py'),run_name='__main__')
    print('EXPORTED',item['id'],len(data['vertices']),flush=True)
(ROOT/'work/owned-assets/catalog/profiles.json').write_text(json.dumps(profiles,indent=2))
