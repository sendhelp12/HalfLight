"""Capture owned assemblies and both anatomical palms in one Half Sword session."""
import json,time,uuid,math
from pathlib import Path
from install_files import save
ROOT=Path(__file__).resolve().parents[1]


def capture(item,index,side='R',calibrate=False):
    nonce=uuid.uuid4().hex[:16];out=ROOT/f'work/lab/catalog-capture-{nonce}.txt'
    request=f'Session={nonce}\nIndex={index}\nExpiresUnix={int(time.time())+25}\nClassPath={item["source_class_path"]}\nSide={side}\nCalibrate={int(calibrate)}\n'
    if item.get('recipe'):request+='Recipe='+item['recipe']+'\n'
    path=ROOT/'work/lab/catalog-capture-request.ini';temporary=path.with_suffix('.tmp')
    temporary.write_text(request,encoding='ascii');temporary.replace(path)
    deadline=time.monotonic()+26;state={}
    while time.monotonic()<deadline:
        if out.exists():
            state=dict(line.split('=',1) for line in out.read_text().splitlines() if '=' in line)
            if state.get('state') in ('captured','error') and state.get('Session')==nonce:break
        time.sleep(.1)
    result={'id':item['id'],'nonce':nonce,'state':state.get('state','timeout'),'error':state.get('error')}
    if result['state']!='captured':raise RuntimeError('Local weapon capture failed: '+str(result['error']))
    print(item['id'],side,'captured',flush=True)
    return result,state


def palm(text):
    values=[float(value) for value in text.split(',')]
    assert len(values)==12 and all(math.isfinite(v) for v in values),'Invalid source palm'
    for row in range(3):
        assert abs(sum(values[row*4+k]**2 for k in range(3))-1)<.002,'Invalid palm orientation'
        assert abs(values[row*4+3])<4,'Palm outside supported weapon bounds'
    for a,b in ((0,1),(0,2),(1,2)):
        assert abs(sum(values[a*4+k]*values[b*4+k] for k in range(3)))<.002,'Skewed palm orientation'
    a,b,c,d,e,f,g,h,i=[values[k] for k in (0,1,2,4,5,6,8,9,10)]
    assert abs(a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)-1)<.002,'Reflected palm orientation'
    return values


def main():
    items=json.loads((ROOT/'work/owned-assets/catalog/selections.json').read_text());results=[];right=None
    for index,item in enumerate(items,1):
        calibrate=item['id']=='sword_g_as60_oh12'
        result,state=capture(item,index,calibrate=calibrate);results.append(result)
        save(ROOT/'work/lab/catalog-capture-results.json',results)
        if calibrate:right=palm(state['palm'])
    reference=next(item for item in items if item['id']=='sword_g_as60_oh12')
    result,state=capture(reference,1,side='L',calibrate=True)
    save(ROOT/'work/lab/native-palm-grip-calibration.json',
         {'profile':reference['id'],'right':right,'left':palm(state['palm']),
          'source':'fresh owned match; actual weapon equipped separately in each hand'})
    print('All assemblies and fresh source palms captured; original equipment restored.')


if __name__=='__main__':main()
