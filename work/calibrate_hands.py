"""Build all grip templates from the fresh campaign rig and locally captured palms."""
import json
import struct
import time
from pathlib import Path
from inspect_retail_hands import run
from retail_bridge import ROOT, attach_reader
from grip_calibration import inverse, multiply, fit, packet
from install_files import save


def main():
    layout=run();reader,loaded,state=attach_reader()
    try:
        assert reader.pid==layout['pid'] and int(state['player'])==layout['player'],'Player changed during calibration'
        runtime=ROOT/'outputs/HalfLightNext/runtime/guest-input.ini'
        assert not runtime.exists() or 'Enabled=1' not in runtime.read_text(),'Disable F8 during calibration'
        skeleton=layout['skeleton'];samples=[]
        for _ in range(12):
            header=reader.read(skeleton+0x2a0,24)
            pointer,count,unused,definition=struct.unpack('<QIIQ',header)
            assert count==390 and definition==layout['buffers'][0]['definition']
            raw=reader.read(pointer,count*48)
            if raw and header==reader.read(skeleton+0x2a0,24):
                models=[struct.unpack_from('<12f',raw,i*48) for i in range(count)]
                local={bone['index']:multiply(inverse(models[bone['parent']]),models[bone['index']])
                       for bone in layout['bones'] if bone['parent']>=0}
                # Prefer the most curled native sample; fitting preserves each joint's length.
                score=sum(3-(local[i][0]+local[i][5]+local[i][10])
                          for i in (*range(26,45),*range(87,106)))
                samples.append((score,local))
            time.sleep(.04)
        assert samples,'No coherent native pose sample'
        local=max(samples,key=lambda item:item[0])[1]
        palms=json.loads((ROOT/'work/lab/native-palm-grip-calibration.json').read_text())
        profiles=json.loads((ROOT/'work/owned-assets/catalog/profiles.json').read_text())
        assert palms['profile']=='sword_g_as60_oh12' and 0<len(profiles)<=32
        staged=ROOT/'.local/grips';staged.mkdir(parents=True,exist_ok=True);files=[]
        for bank in range(2*len(profiles)):
            profile=profiles[bank%len(profiles)]
            path=(ROOT/profile['geometry_path']).resolve()
            assert path.is_relative_to((ROOT/'work/owned-assets').resolve()),'Geometry escapes owned assets'
            geometry=json.loads(path.read_text())
            for side,suffix in (('right',''),('left','left-')):
                values=fit(profile,geometry,layout['bones'],local,palms[side],side)
                name=f'native-axe-{suffix}grip-setup-{bank}.config'
                (staged/name).write_bytes(packet(*values));files.append(name)
        current,_,fresh=attach_reader()
        try:assert current.pid==reader.pid and int(fresh['player'])==layout['player'],'Player changed during calibration'
        finally:current.close()
        assert reader.number(skeleton+8)==layout['handle']
        for name in files:
            (staged/name).replace(ROOT/'work/lab'/name)
        save(ROOT/'.local/hand-calibration.json',{'phase':'prepared','rig':layout['rig'],
             'banks':len(profiles)*2,'templates':len(files),'source':'fresh campaign and owned source palms'})
        print('Prepared fresh grip templates for every weapon and hand. Live attachment remains to be verified.')
    finally:reader.close()


if __name__=='__main__':main()
