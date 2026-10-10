"""Publish locally observed profiles for both runtime readers."""
import json
from setup import ROOT
from install_files import save


def publish(profiles,root=ROOT):
    if not profiles or len(profiles)>32 or len({p['id'] for p in profiles})!=len(profiles):
        raise ValueError('Invalid local catalogue')
    lines=['Version=1','Count='+str(len(profiles))]
    for i,p in enumerate(profiles):
        prefix='Weapon.'+str(i)+'.'
        for key,field in (('Id','id'),('Class','actor_class'),('Component','component'),
                          ('Offset','pose_offset_cm'),('Path','source_class_path'),('Recipe','recipe')):
            if field in p:lines.append(prefix+key+'='+str(p[field]))
        lines.append(prefix+'Scale='+','.join(map(str,p['source_scale'])))
        lines.extend(prefix+'Part.'+label+'='+asset for label,asset in p['source_parts'].items())
        lines.extend(prefix+'PartScale.'+label+'='+','.join(map(str,scale))
                     for label,scale in p['source_part_scales'].items())
    if any('\n' in line or '\r' in line for line in lines):raise ValueError('Invalid catalogue field')
    private=root/'.local';private.mkdir(exist_ok=True)
    temporary=private/'catalog.ini.tmp';temporary.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    save(private/'catalog.json',{'version':1,'weapons':profiles})
    temporary.replace(private/'catalog.ini')


if __name__=='__main__':publish(json.loads((ROOT/'work/owned-assets/catalog/profiles.json').read_text()))
