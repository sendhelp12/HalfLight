"""Export the owned, observed modular sword with the proven official exporter."""
import hashlib,json,os,sys
from pathlib import Path
sys.dont_write_bytecode=True
import bpy,addon_utils
from mathutils import Vector
root=Path(__file__).resolve().parents[2]
args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
source=root/args[0] if args else root/'work/owned-assets/sword/sword.json'
assert source.resolve().is_relative_to(root/'work/owned-assets')
out=source.parent/'native';out.mkdir(exist_ok=True)
data=json.loads(source.read_text());assert data['format']=='HalfLightStaticMesh1' and data['source'].startswith('owned-equipped-')
assert bpy.app.version[:2]==(3,6);name=args[1] if args else 'halflight_guest_sword'
sys.path.insert(0,str(root/'work'))
from release_paths import local_path
exporter=Path(local_path('dying_light','DevTools/dcc/blender/techland_msh_exporter'))
bpy.ops.wm.read_factory_settings(use_empty=True);dll_directory=os.add_dll_directory(str(exporter));sys.path.insert(0,str(exporter.parent))
addon_utils.enable('techland_msh_exporter',default_set=True,persistent=False)
prefs=bpy.context.preferences.addons['techland_msh_exporter'].preferences;prefs.summary_on_success=False;prefs.show_callstack=True
vertices=[(v[0]*.01,-v[1]*.01,v[2]*.01) for v in data['vertices']]
normals=[Vector((n[0],-n[1],n[2])).normalized() for n in data['normals']]
faces=[tuple(data['indices'][i:i+3]) for i in range(0,len(data['indices']),3)]
signs=[]
for face in faces:
    a,b,c=(Vector(vertices[i]) for i in face);dot=(b-a).cross(c-a).dot(sum((normals[i] for i in face),Vector()))
    if abs(dot)>1e-10:signs.append(dot>0)
fraction=sum(signs)/len(signs);assert fraction<.02 or fraction>.98,'Inconsistent source normals/winding'
if fraction<.5:faces=[(a,c,b) for a,b,c in faces]
mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices,[],faces);mesh.update()
obj=bpy.data.objects.new(name+'_0',mesh);bpy.context.collection.objects.link(obj);bpy.context.view_layer.objects.active=obj;obj.select_set(True)
uv=mesh.uv_layers.new(name='UVMap')
for loop in mesh.loops:u,v=data['uvs'][loop.vertex_index];uv.data[loop.index].uv=(u,1-v)
colors=mesh.vertex_colors.new(name='Color')
for color in colors.data:color.color=(1,1,1,1)
for polygon in mesh.polygons:polygon.use_smooth=True
mesh.use_auto_smooth=True;mesh.normals_split_custom_set_from_vertices(normals)
materials=data.get('material_indices',{'Pommel':0,'Guard':0,'Head':0,'Grip':1})
material_names=('example_steel_rough','wn_machete_b_leather','wood_panel_a_dark')
for material in material_names:
    mesh.materials.append(bpy.data.materials.new(material))
covered=set()
for section in data['sections']:
    first=section['FirstIndex'];count=section['NumTriangles']
    assert first%3==0 and section['part'] in materials
    for index in range(first//3,first//3+count):
        assert index<len(mesh.polygons) and index not in covered
        covered.add(index);mesh.polygons[index].material_index=materials[section['part']]
assert len(covered)==len(mesh.polygons)
bpy.context.scene.unit_settings.system='METRIC';bpy.ops.wm.save_as_mainfile(filepath=str(out/(name+'.blend')))
result=bpy.ops.export_scene.msh(filepath=str(out/(name+'.msh')),export_selected=True,move_to_zero=True,use_filename_name=True,save_skn_file=True,auto_generate_trace_hull=False,generate_collision_from_trace=False,apply_modifiers=False,copy_uv0_to_uv1=True)
from techland_msh_exporter.main import EXPORT_GLOBALS
assert not any(row[0]=='Error' for row in EXPORT_GLOBALS.summary),EXPORT_GLOBALS.summary
manifest={'status':'exported','vertices':len(vertices),'triangles':len(faces),'dimensions_metres':list(obj.dimensions),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'pivot':'verified live pose component; component scales and offsets baked once','materials':{str(index):name for index,name in enumerate(material_names) if index in set(materials.values())},
    'files':{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in out.iterdir() if p.stem==name and p.suffix in ('.msh','.skn','.blend')}}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest))
