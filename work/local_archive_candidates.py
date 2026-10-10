"""Scan the owned executable for immediate stores; validate candidates by mounting locally."""
import json
import re
from pathlib import Path
from pe_tools import PE
from setup import ROOT, validate
from install_files import save


def candidates(data):
    stores=[]
    # C7 /0 writes a 32-bit immediate to memory. Decode ordinary base+displacement forms.
    for match in re.finditer(b'\xc7[\x00-\x04\x06-\x07\x40-\x47\x80-\x87]',data):
        start=match.start();mode=data[start+1]>>6;base=data[start+1]&7;offset=start+2
        if base==4:
            if offset>=len(data) or data[offset]!=0x24:continue
            offset+=1
        width=0 if mode==0 else 1 if mode==1 else 4
        if offset+width+4>len(data):continue
        displacement=int.from_bytes(data[offset:offset+width],'little',signed=True)
        offset+=width
        stores.append((start,offset+4,base,displacement,data[offset:offset+4]))
    found=set()
    for index in range(len(stores)-7):
        group=stores[index:index+8]
        if len({row[2] for row in group})!=1 or any(b[0]-a[1]>16 for a,b in zip(group,group[1:])):continue
        ordered=sorted(group,key=lambda row:row[3])
        if any(b[3]-a[3]!=4 for a,b in zip(ordered,ordered[1:])):continue
        key=b''.join(row[4] for row in ordered)
        if len(set(key))>=16:found.add(key.hex())
    return sorted(found)


if __name__=='__main__':
    config=json.loads((ROOT/'.local/install.json').read_text())
    paths=validate(Path(config['half_sword']),Path(config['dying_light']))
    pe=PE(paths['HalfSwordUE5-Win64-Shipping.exe'])
    text=next(section for section in pe.sections if section['name']=='.text')
    result=candidates(pe.data[text['raw']:text['raw']+text['size']])
    if not result:raise RuntimeError('Local archive-key scan unsupported; no assets extracted')
    save(ROOT/'work/lab/owned-archive-key-candidates.json',result)
    print('Local archive candidates saved privately:',len(result),'. Archive mounting must validate them.')
