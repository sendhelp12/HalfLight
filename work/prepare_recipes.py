"""Read forge defaults from locally extracted definitions; ship no passport dumps."""
import json
from pathlib import Path
from setup import ROOT
from install_files import save

FORGED={'longsword':'Sword_Long','messer':'Messer','hafted_short':'Hafted_Short',
        'hafted_long':'Hafted_Long','mace_short':'Mace_Short','mace_long':'Mace_Long',
        'polearm':'Polearm','poleaxe':'Pollaxe'}


def properties(folder, name, seen=()):
    if name in seen or Path(name).name != name:
        raise ValueError('Invalid or cyclic local definition inheritance')
    rows=json.loads((Path(folder)/(name+'.json')).read_text(encoding='utf-8'))
    parent=next(row for row in rows if row['Type']=='BlueprintGeneratedClass').get('SuperStruct',{}).get('ObjectPath','')
    result=properties(folder,Path(parent.rsplit('.',1)[0]).name,seen+(name,)) if parent.startswith('Halfsword') else {}
    for row in rows:
        if row['Name'].startswith('Default__'):
            result.update(row.get('Properties',{}))
    return result


def object_path(reference):
    path=reference['ObjectPath'].rsplit('.',1)[0].replace('HalfswordUE5/Content/','/Game/')
    if not path.startswith('/Game/'):
        raise ValueError('Invalid local module reference')
    return {'object':path+'.'+Path(path).name+'_C'}


def lua(value):
    if value is None:return 'nil'
    if isinstance(value,bool):return 'true' if value else 'false'
    if isinstance(value,(int,float,str)):return json.dumps(value)
    if isinstance(value,dict):return '{'+','.join('['+lua(k)+']='+lua(v) for k,v in value.items())+'}'
    raise ValueError('Unsupported local forge field type')


def prepare(folder, selections):
    base=properties(folder,'ModularWeaponBP')['Weapon Passport']
    keys={field.split('_')[0]:field for field in base}
    if len(keys)!=len(base):raise ValueError('Ambiguous forge field names')
    recipes={}
    for item in selections:
        if not item.get('recipe'):continue
        identifier=item['id'];passport={}
        for field,default in base.items():
            name=field.split('_')[0]
            if name.endswith('Size'):value={'X':1,'Y':1,'Z':1}
            elif name.startswith('CustomMassScale'):value=1
            elif name in ('ColorWood','ColorLeather'):value={'R':1,'G':1,'B':1,'A':1}
            elif isinstance(default,str) and '::NewEnumerator' in default:value=int(default.rsplit('NewEnumerator',1)[1])
            else:value=default
            if value is not None:passport[field]=value
        passport[keys['WeaponClass']]={'object':item['source_class_path']+'.ModularWeaponBP_C'}
        passport[keys['Name']]=item['label']
        if identifier=='sword_g_as60_oh12':
            # The curated assembly choices are mod configuration; native field IDs come from local data.
            modules={'HeadModule':'Blade/Modular_Sword_Blade_G_60',
                     'GuardModule':'Guard/Weapon_Sword_Guard_GA',
                     'GripModule':'Grips/Weapon_Sword_Grip_12_T2',
                     'PommelModule':'Pommels/Weapon_Sword_Pommel_A'}
            for field,suffix in modules.items():
                path='/Game/Assets/Weapons/Swords/Modules/'+suffix
                passport[keys[field]]={'object':path+'.'+Path(path).name+'_C'}
            passport[keys['HeadSize']]={'X':1,'Y':.5,'Z':1}
            passport[keys['GripSize']]={'X':.75,'Y':.5,'Z':1}
            for field,value in (('MaterialMetalSteel',11),('MaterialMetalColored',4),('MaterialWeood',3),('MaterialLeather',2)):
                passport[keys[field]]=value
        else:
            archetype=FORGED[identifier]
            data=properties(folder,'BP_GameWeapon_Customizable_'+archetype)
            arrays={'HeadModule':'Head Sub Module 2 Array' if identifier=='longsword' else 'Module Heads Array',
                    'GripModule':'Module Grips Array','GuardModule':'Module Guards Array','PommelModule':'Module Pommels Array'}
            if identifier=='poleaxe':arrays.update(HeadSubModule1='Head Sub Module 1 Array',HeadSubModule2='Head Sub Module 2 Array')
            for field,array in arrays.items():
                options=data.get(array,[])
                if not options:continue
                selected=next((value for value in options if value and '_Axe' in value['ObjectPath']),options[0]) if field.startswith('HeadSub') else options[0]
                if selected:passport[keys[field]]=object_path(selected)
        recipes[item['recipe']]=passport
    return recipes


if __name__=='__main__':
    folder=ROOT/'work/owned-assets/catalog'
    selections=json.loads((ROOT/'profiles/weapons.json').read_text())
    recipes=prepare(folder/'definitions',selections)
    save(folder/'selections.json',selections)
    save(folder/'recipes.json',recipes)
    output=ROOT/'work/lab/catalog-recipes.lua';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('return '+lua(recipes)+'\n',encoding='utf-8')
    print('Prepared',len(selections),'weapons from local definitions; game files unchanged.')
