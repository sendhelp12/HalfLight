"""Installer/audit boundary regressions; never require or operate a game."""
import hashlib
import importlib.util
import json
import tempfile
import subprocess
import sys
import zipfile
import unittest
from types import SimpleNamespace
import ssl
import urllib.error
from unittest.mock import patch
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'work'))
TEMP=ROOT/".local/tests"
TEMP.mkdir(parents=True,exist_ok=True)

def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'work'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

setup=load('setup');audit=load('release_audit');paths=load('release_paths')
installation=load('install_files')
archives=load('local_archive_candidates');recipes=load('prepare_recipes')
tools=load('get_tools')
loader=load('install_loader')
capture=load('capture_catalog');grips=load('grip_calibration')
catalog=load('publish_catalog');cooking=load('cook_assets')

class ReleaseTests(unittest.TestCase):
    def test_equipment_check_requires_matching_native_acknowledgement(self):
        equipment=load('verify_equipping')
        with tempfile.TemporaryDirectory(dir=TEMP) as folder,patch.object(equipment,'ROOT',Path(folder)),patch.object(equipment,'LAB',Path(folder)):
            root=Path(folder);(root/'.local').mkdir()
            installation.save(root/'.local/catalog.json',{'weapons':[{'id':'fixture'}]})
            initial={'request_sequence':'7'}
            ack={'Session':'fixture','request_sequence':'8','state':'applied','right':'fixture','left':'none'}
            with patch.object(equipment,'fields',side_effect=[initial,ack]):equipment.equip('fixture','fixture','none')
            self.assertIn('seq=8',(root/'weapon-menu-request-fixture.txt').read_text())
            with patch.object(equipment,'fields',side_effect=[initial,dict(ack,left='fixture')]):
                with self.assertRaises(AssertionError):equipment.equip('fixture','fixture','none')
            with patch.object(equipment,'fields',side_effect=[initial,dict(ack,state='error',error='fixture failure')]):
                with self.assertRaisesRegex(RuntimeError,'fixture failure'):equipment.equip('fixture','fixture','none')
            with patch.object(equipment,'fields',return_value=initial),patch.object(equipment.time,'monotonic',side_effect=[0,0,2]),patch.object(equipment.time,'sleep'):
                with self.assertRaises(TimeoutError):equipment.equip('fixture','fixture','none',timeout=1)

    def test_panel_restarts_only_when_status_or_owned_process_is_lost(self):
        panel=load('campaign_control')
        with tempfile.TemporaryDirectory(dir=TEMP) as folder,patch.object(panel,'OUT',Path(folder)),patch.object(panel,'processes',return_value={10:'python.exe',11:'powershell.exe'}),patch.object(panel.subprocess,'Popen') as start:
            status={'updated_at':panel.time.time(),'panel_pid':10,'panel_ui_pid':11}
            with patch.object(panel,'read_json',return_value=status):panel.ensure_panel()
            start.assert_not_called()
            with patch.object(panel,'read_json',return_value=dict(status,updated_at=0)):panel.ensure_panel()
            start.assert_called_once()
            start.reset_mock()
            with patch.object(panel,'read_json',return_value=dict(status,panel_ui_pid=12)):panel.ensure_panel()
            start.assert_called_once()

    def test_asset_resume_recovers_config_after_journal_was_saved_first(self):
        assets=load('install_assets')
        with tempfile.TemporaryDirectory(dir=TEMP) as folder,patch.object(assets,'ROOT',Path(folder)),patch.object(assets,'validate'):
            root=Path(folder);private=root/'.local';private.mkdir()
            local=private/'assets/meshes';local.mkdir(parents=True)
            game=root/'game';target=game/'halflight-fixture/meshes';target.mkdir(parents=True)
            name='halflight_fixture.msh_obj';(local/name).write_bytes(b'fixture');(target/name).write_bytes(b'fixture')
            checksum=installation.digest(local/name)
            installation.save(private/'install.json',{'half_sword':'fixture','dying_light':'fixture'})
            installation.save(private/'catalog.json',{'weapons':[{}]})
            installation.save(private/'cooked-assets.json',{'banks':2})
            installation.save(private/'assets-files.json',{'phase':'installed','roots':{'dying_light':str(game)},
                'files':[{'root':'dying_light','relative':'halflight-fixture/meshes/'+name,'sha256':checksum}]})
            assets.main()
            self.assertEqual(json.loads((private/'install.json').read_text())['asset_root'],str(target.parent.resolve()))

    def test_successful_uninstall_clears_ready_state_and_capture_session(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);private=root/'.local';private.mkdir()
            installation.save(private/'install.json',{'ready':True,'capture_session':'fixture','asset_root':'fixture'})
            namespace={'__name__':'__main__','__file__':str(root/'work/install_files.py')}
            with patch.object(sys,'argv',['install_files.py','--uninstall']),patch('subprocess.run',return_value=SimpleNamespace(stdout='')):
                exec(compile((ROOT/'work/install_files.py').read_text(),namespace['__file__'],'exec'),namespace)
            state=json.loads((private/'install.json').read_text())
            self.assertFalse(state['ready']);self.assertNotIn('capture_session',state);self.assertNotIn('asset_root',state)

    def test_setup_requires_fresh_components_not_just_a_controller_process(self):
        complete=load('complete_setup')
        states={'Source poses':'Fresh','World rendering':'Off','Camera sync':'Fresh','Weapon and hand adapter':'Active',
                'Input / vanilla attack filter':'Active','Weapon equipping':'Ready',
                'Dropped weapon cleanup':'Active; removed 0'}
        status={'connected':True,'errors':[],'rows':[{'part':k,'state':v} for k,v in states.items()]}
        self.assertTrue(complete.components_ready(status))
        for row in status['rows']:
            original=row['state'];row['state']='Waiting'
            self.assertFalse(complete.components_ready(status))
            row['state']=original
        self.assertFalse(complete.components_ready(dict(status,errors=['fixture failure'])))

    def test_pre_hook_mapping_refusal_requires_verified_slots_and_no_active_damage_adapter(self):
        bridge=load('run_retail_bridge')
        with tempfile.TemporaryDirectory(dir=TEMP) as folder,patch.object(bridge,'LAB',Path(folder)):
            (Path(folder)/'native-axe-damage-123.log').write_text('status,offhand_mapping_refused\n')
            active={'target_pid':123,'callback_restored':True,'weapons_restored':True,'session':'fixture'}
            self.assertTrue(bridge.recovery_allowed(active,{123:'game.exe'}))
            with self.assertRaises(RuntimeError):
                bridge.recovery_allowed(dict(active,callback_restored=False),{123:'game.exe'})
            with self.assertRaises(RuntimeError):
                bridge.recovery_allowed(dict(active,damage_dll='active.dll'),{123:'game.exe'})

    def test_weapon_impact_profiles_cover_every_family_and_reject_invalid_calibration(self):
        combat=load('combat_profile')
        import struct
        for family,index in combat.families.items():
            profile={'family':family,'id':'fixture','cutting_segment_m':[[0,0,0],[1,0,0]]}
            packet=combat.combat_profile(profile)
            self.assertEqual(struct.unpack('<I3f',packet)[0],index)
            with self.assertRaises(AssertionError):
                combat.combat_profile(dict(profile,combat={'mass_kg':float('nan')}))

    def test_campaign_loader_uses_shared_function_without_development_templates(self):
        bridge=load('retail_bridge')
        reader=SimpleNamespace(pid=123);dll=Path('fixture.dll')
        with patch('native_loader.load_native') as native,patch.object(bridge,'modules',return_value={}) as modules:
            bridge.load_native(reader,{},dll,10,20)
            self.assertEqual(native.call_args.args[:5],(reader,{},dll,10,20))
            self.assertEqual(native.call_args.args[5](),{})
            modules.assert_called_once_with(123)

    def test_local_catalogue_keeps_source_metadata_private_and_rejects_newlines(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder)
            profile={'id':'fixture','actor_class':'Fixture_C','component':'Blade','pose_offset_cm':0,
                     'source_scale':[1,1,1],'source_parts':{'Blade':'/Game/Fixture'},'source_part_scales':{}}
            catalog.publish([profile],root)
            self.assertIn('Weapon.0.Part.Blade=/Game/Fixture',(root/'.local/catalog.ini').read_text())
            profile['id']='fixture\nCount=99'
            with self.assertRaises(ValueError):catalog.publish([profile],root)
            self.assertEqual(json.loads((root/'.local/catalog.json').read_text())['weapons'][0]['id'],'fixture')

    def test_cooking_checks_fresh_source_identity_and_material_dependencies(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);project=root/'sdk/projects/local/HalfLightSetup'
            source=project/'source/data/Meshes';compiled=project/'work/data_platform/pc/assets/meshes'
            source.mkdir(parents=True);compiled.mkdir(parents=True)
            mesh=source/'halflight_fixture.msh';mesh.write_bytes(b'authored fixture')
            (source/'halflight_fixture.skn').write_text('Replace("fixture.mat", "fixture.mat")')
            (compiled/'halflight_fixture.msh_obj').write_bytes(b'compiled fixture')
            dependency=compiled/'halflight_fixture.msh_obj_dep'
            dependency.write_text('Source("meshes/halflight_fixture.msh", "0")\nUsedFile("fixture&0004.mat", "0")')
            manifest={'devtools':str(root/'sdk'),'directory':'HalfLightSetup',
                      'files':[{'name':mesh.name,'sha256':setup.digest(mesh)}]}
            self.assertEqual(len(cooking.verify(manifest,root)),2)
            dependency.write_text('Source("meshes/another.msh", "0")')
            with self.assertRaisesRegex(AssertionError,'wrong source identity'):cooking.verify(manifest,root)

    def test_verified_windows_download_and_existing_tool_adoption(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);archive=root/'fixture.zip'
            with zipfile.ZipFile(archive,'w') as package:package.writestr('enclosing/tool.txt','verified')
            spec={'url':'https://example.invalid/fixture.zip','sha256':setup.digest(archive)}
            destination=root/'.local/tools/fixture';destination.mkdir(parents=True)
            (destination/'tool.txt').write_text('verified')
            def download(command,**kwargs):
                self.assertNotIn('--insecure',command)
                Path(command[command.index('--output')+1]).write_bytes(archive.read_bytes())
            with patch.object(tools,'ROOT',root),patch.object(tools.urllib.request,'urlopen',
                    side_effect=urllib.error.URLError(ssl.SSLCertVerificationError('certificate'))),\
                    patch.object(tools.subprocess,'run',side_effect=download):
                self.assertEqual(tools.fetch('fixture',spec),destination)
            (root/'.local/tools/fixture.verified.json').unlink()
            (destination/'tool.txt').write_text('user change')
            with patch.object(tools,'ROOT',root),self.assertRaisesRegex(ValueError,'Preserving an existing'):
                tools.fetch('fixture',spec)
            self.assertEqual((destination/'tool.txt').read_text(),'user change')

    def test_known_predecessor_update_is_backed_up_and_uninstall_restores_it(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);source=root/'new.lua';old=root/'main.lua';journal=root/'files.json'
            source.write_text('new authored loader');old.write_text('known authored loader')
            previous=setup.digest(old)
            files=[{'source':str(source),'root':'game','relative':'main.lua',
                    'sha256':setup.digest(source),'replace_sha256':previous}]
            installation.install({'game':root},files,journal)
            self.assertEqual(old.read_text(),'new authored loader')
            self.assertEqual(installation.uninstall(journal),[])
            self.assertEqual(old.read_text(),'known authored loader')
            old.write_text('another mod')
            with self.assertRaisesRegex(ValueError,'Preserving differing'):
                installation.install({'game':root},files,journal)
            self.assertEqual(old.read_text(),'another mod')

    def test_fresh_palm_and_finger_fit_reject_invalid_geometry(self):
        identity=[1,0,0,0,0,1,0,0,0,0,1,0]
        self.assertEqual(capture.palm(','.join(map(str,identity))),identity)
        for values in (identity[:11],identity[:3]+[float('nan')]+identity[4:],
                       [-1]+identity[1:],identity[:3]+[5]+identity[4:]):
            with self.assertRaises(AssertionError):capture.palm(','.join(map(str,values)))
        elbow,wrist=grips.solve((0,0,0),(0,.04,0),(0,.08,0),(.02,.06,0))
        self.assertAlmostEqual(grips.length(elbow),.04)
        self.assertAlmostEqual(grips.length(grips.sub(wrist,elbow)),.04)
        data=grips.packet(identity,identity,[{'index':10,'parent':9}],{})
        self.assertEqual(len(data),200)
        self.assertEqual(data[8:40],bytes(32))

    def test_loader_install_preserves_other_mods_and_uninstalls_only_owned_files(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);game=root/'game';package=root/'package';source=root/'source'
            for base in (game,package):
                (base/'ue4ss').mkdir(parents=True)
            for name in ('dwmapi.dll','ue4ss/UE4SS.dll','ue4ss/LICENSE','ue4ss/UE4SS-settings.ini'):
                (package/name).write_text('ConsoleEnabled = 1\nGuiConsoleEnabled = 1\n')
            (game/'ue4ss/UE4SS-settings.ini').write_text('user settings')
            (game/'ue4ss/Mods').mkdir();(game/'ue4ss/Mods/mods.txt').write_text('OtherMod : 1')
            (source/'loader').mkdir(parents=True)
            (source/'loader/main.lua').write_text('return true')
            (source/'loader/actor_capture.lua').write_text('return true')
            files=loader.prepare(game,package,source)
            journal=root/'files.json'
            installation.install({'half_sword':game},files,journal)
            self.assertEqual((game/'ue4ss/Mods/mods.txt').read_text(),'OtherMod : 1')
            self.assertEqual((game/'ue4ss/UE4SS-settings.ini').read_text(),'user settings')
            self.assertTrue((game/'ue4ss/Mods/HalfLightBridge/enabled.txt').exists())
            session=loader.initialize_capture(source)
            runtime=source/'outputs/HalfLightNext/runtime'
            self.assertEqual((runtime/'setup-mapping.request').read_text(),session)
            self.assertIn('Enabled=0',(runtime/'guest-input.ini').read_text())
            self.assertEqual(installation.uninstall(journal),[])
            self.assertFalse((game/'dwmapi.dll').exists())
            self.assertEqual((game/'ue4ss/Mods/mods.txt').read_text(),'OtherMod : 1')

    def test_tool_archives_reject_bad_checksum_and_traversal_before_writing(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);archive=root/'tool.zip';target=root/'tool'
            with zipfile.ZipFile(archive,'w') as package:package.writestr('../escape.py','fixture')
            with self.assertRaisesRegex(ValueError,'checksum'):
                tools.verified_archive(archive,target,'0'*64)
            with self.assertRaisesRegex(ValueError,'archive path'):
                tools.verified_archive(archive,target,setup.digest(archive))
            self.assertFalse(target.exists());self.assertFalse((root/'escape.py').exists())
            with zipfile.ZipFile(archive,'w') as package:package.writestr('valid/LICENSE','fixture notice')
            tools.verified_archive(archive,target,setup.digest(archive))
            self.assertEqual((target/'valid/LICENSE').read_text(),'fixture notice')

    def test_local_candidate_stores_require_contiguous_memory(self):
        key=bytes(range(32))
        code=b''.join(b'\xc7\x45'+bytes([16+i*4])+key[i*4:i*4+4] for i in range(8))
        self.assertIn(key.hex(),archives.candidates(code))
        zero_base=b'\xc7\x01'+key[:4]+b''.join(b'\xc7\x41'+bytes([i*4])+key[i*4:i*4+4] for i in range(1,8))
        self.assertIn(key.hex(),archives.candidates(zero_base))
        self.assertFalse(archives.candidates(code[:-1]))
        self.assertFalse(archives.candidates(code.replace(b'\xc7\x45\x2c',b'\xc7\x45\x30')))

    def test_forge_fields_and_inheritance_come_from_local_definition(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder)
            def write(name,props,parent=''):
                (root/(name+'.json')).write_text(json.dumps([
                    {'Type':'BlueprintGeneratedClass','Name':name+'_C','SuperStruct':{'ObjectPath':parent}},
                    {'Type':'DefaultObject','Name':'Default__'+name,'Properties':props}]))
            fields={'WeaponClass_local':None,'Name_local':'default','HeadModule_local':None,'HeadSize_local':{'X':2},'CustomMassScaleHead_local':4}
            write('ModularWeaponBP',{'Weapon Passport':fields})
            write('BP_GameWeapon_Customizable_Messer',{'Module Heads Array':[{'ObjectPath':'HalfswordUE5/Content/Weapons/Head.Head_C'}]})
            result=recipes.prepare(root,[{'id':'messer','recipe':'messer','label':'Messer','source_class_path':'/Game/Weapons/ModularWeaponBP'}])['messer']
            self.assertEqual(result['HeadModule_local']['object'],'/Game/Weapons/Head.Head_C')
            self.assertEqual(result['HeadSize_local'],{'X':1,'Y':1,'Z':1})
            write('Cycle',{},'HalfswordUE5/Content/Cycle.Cycle_C')
            with self.assertRaisesRegex(ValueError,'cyclic'):recipes.properties(root,'Cycle')

    def test_install_refuses_conflicts_and_preserves_modified_files(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);game=root/'game';game.mkdir();source=root/'source'
            source.write_bytes(b'our code');journal=root/'journal.json'
            row={'source':str(source),'root':'game','relative':'mod/main.lua','sha256':setup.digest(source)}
            installation.install({'game':game},[row],journal)
            installed=game/'mod/main.lua';self.assertEqual(installed.read_bytes(),source.read_bytes())
            installed.write_bytes(b'user edit')
            self.assertEqual(installation.uninstall(journal),['mod/main.lua'])
            self.assertEqual(installed.read_bytes(),b'user edit')
            journal.unlink()
            with self.assertRaisesRegex(ValueError,'differing existing file'):
                installation.install({'game':game},[row],journal)
            self.assertFalse(journal.exists())

    def test_install_rolls_back_and_does_not_own_existing_matching_files(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);game=root/'game';game.mkdir();source=root/'source';source.write_bytes(b'fixture')
            (game/'existing.lua').write_bytes(source.read_bytes());journal=root/'journal.json'
            rows=[{'source':str(source),'root':'game','relative':name,'sha256':setup.digest(source)}
                  for name in ('existing.lua','first.lua','second.lua')]
            rename=installation.os.rename;count=0
            def fail_second(*args):
                nonlocal count
                count+=1
                if count==2:raise OSError('fixture failure')
                return rename(*args)
            with patch.object(installation.os,'rename',side_effect=fail_second):
                with self.assertRaises(OSError):installation.install({'game':game},rows,journal)
            self.assertTrue((game/'existing.lua').exists());self.assertFalse((game/'first.lua').exists())
            self.assertEqual(json.loads(journal.read_text())['phase'],'removed')
            with self.assertRaises(ValueError):installation.destination(game,'../escape.lua')

    def test_owned_builds_and_wrong_build_refusal(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder);hs=root/'guest';dl=root/'host'
            files={
                'HalfSwordUE5-Win64-Shipping.exe':hs/'HalfSwordUE5/Binaries/Win64/HalfSwordUE5-Win64-Shipping.exe',
                'DyingLightGame_x64_rwdi.exe':dl/'ph/work/bin/x64/DyingLightGame_x64_rwdi.exe',
                'engine_x64_rwdi.dll':dl/'ph/work/bin/x64/engine_x64_rwdi.dll'}
            for name,p in files.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
            pak=hs/'HalfSwordUE5/Content/Paks/pakchunk0-Windows.pak';pak.parent.mkdir(parents=True);pak.write_bytes(b'local fixture')
            exporter=dl/'DevTools/dcc/blender/techland_msh_exporter';exporter.mkdir(parents=True)
            (dl/'DevTools/version.txt').write_text('fixture')
            profile={'games':{},'modules':{},'devtools_version':'fixture'}
            for name,p in files.items():profile['modules' if name.endswith('.dll') else 'games'][name]={'sha256':setup.digest(p)}
            self.assertEqual(set(setup.validate(hs,dl,profile)),set(files))
            files['engine_x64_rwdi.dll'].write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'Unsupported game build'):setup.validate(hs,dl,profile)
            self.assertFalse((root/'.local').exists())

    def test_paths_cannot_escape(self):
        with self.assertRaises(ValueError):paths.local_path('root','../outside')
        self.assertEqual(Path(paths.local_path('root','profiles')),ROOT/'profiles')

    def test_game_data_and_private_text_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder)
            (root/'README.md').write_text('Project documentation')
            failures,entries=audit.audit(root);self.assertFalse(failures);self.assertEqual(len(entries),1)
            (root/'mesh.msh_obj').write_bytes(b'game fixture')
            (root/'private.py').write_text('path='+repr('C:'+chr(92)+'Users'+chr(92)+'Example'+chr(92)+'private'))
            failures,_=audit.audit(root)
            self.assertTrue(any('Non-source' in f for f in failures))
            self.assertTrue(any('personal Windows path' in f for f in failures))

    def test_deleted_game_file_is_still_rejected_in_history(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder)
            def git(*args):
                return subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture'+chr(64)+'example.invalid',*args],cwd=root,check=True,capture_output=True)
            git('init','-q')
            (root/'README.md').write_text('Source fixture')
            (root/'old.msh_obj').write_bytes(b'\0game fixture')
            git('add','.');git('commit','-qm','Fixture')
            (root/'old.msh_obj').unlink();git('add','-u');git('commit','-qm','Remove fixture')
            failures,_=audit.audit(root);self.assertFalse(failures)
            self.assertTrue(any('old.msh_obj' in f for f in audit.history_audit(root)))

    def test_staged_private_content_cannot_hide_behind_a_clean_working_file(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder)
            subprocess.run(['git','init','-q'],cwd=root,check=True,capture_output=True)
            source=root/'README.md'
            source.write_text('path='+repr('C:'+chr(92)+'Users'+chr(92)+'Example'+chr(92)+'private'))
            subprocess.run(['git','add','.'],cwd=root,check=True,capture_output=True)
            source.write_text('Clean source fixture')
            self.assertFalse(audit.audit(root)[0])
            self.assertTrue(any('personal Windows path' in f for f in audit.staged_audit(root)))

    def test_git_metadata_requires_anonymous_identity(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as folder:
            root=Path(folder)
            def git(*args):
                return subprocess.run(['git','-c','user.name=HalfLight contributors',
                    '-c','user.email=release'+chr(64)+'example.invalid',*args],cwd=root,check=True,capture_output=True)
            git('init','-q');(root/'README.md').write_text('Source fixture')
            git('add','.');git('commit','-qm','Source fixture')
            self.assertFalse(audit.metadata_audit(root))
            git('commit','--allow-empty','-qm','Fixture identity','--author','Personal Name <person'+chr(64)+'example.invalid>')
            self.assertTrue(audit.metadata_audit(root))

if __name__=='__main__':unittest.main()
