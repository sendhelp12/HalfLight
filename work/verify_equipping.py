"""Verify native menu equipment without injecting gameplay input."""
import json,time
from campaign_control import LAB,fields,health
from install_files import save
from setup import ROOT


def equip(session,right,left,timeout=10):
    ids={p['id'] for p in json.loads((ROOT/'.local/catalog.json').read_text())['weapons']}|{'none'}
    assert right in ids and left in ids
    status_path=LAB/f'weapon-menu-status-{session}.txt'
    sequence=int(fields(status_path,age=float('inf')).get('request_sequence','0'))+1
    request=LAB/f'weapon-menu-request-{session}.txt'
    temporary=request.with_suffix('.tmp')
    temporary.write_text(f'Session={session}\nseq={sequence}\nend_seq={sequence}\nexpires_at={int(time.time())+15}\nright={right}\nleft={left}\n')
    temporary.replace(request)
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        status=fields(status_path,age=float('inf'))
        if status.get('Session')==session and status.get('request_sequence')==str(sequence):
            if status.get('state')=='error':raise RuntimeError(status.get('error','Native equip failed'))
            if status.get('state')=='applied':
                assert (status.get('right'),status.get('left'))==(right,left),'Native menu acknowledgement has wrong equipment'
                return
        time.sleep(.1)
    raise TimeoutError('Native weapon menu did not acknowledge '+right+' / '+left)


def run():
    status=health();assert status['connected']
    assert next(row['state'] for row in status['rows'] if row['part']=='F8 control')=='Off','Equip verification requires F8 off'
    session=status['session'];previous=fields(LAB/f'weapon-menu-status-{session}.txt',age=float('inf'))
    original=(previous['right'],previous['left'])
    verified=[]
    try:
        for profile in json.loads((ROOT/'.local/catalog.json').read_text())['weapons']:
            identifier=profile['id'];equip(session,identifier,identifier)
            verified.append(identifier);print('PASS native duplicate pair:',identifier,flush=True)
    finally:
        equip(session,*original)
    save(ROOT/'.local/equipment-verification.json',{'weapons':verified,'both_hands':True,
        'equipment_restored':True,'gameplay_input_injected':False})
    print('PASS every weapon in both independent hands; previous equipment restored',flush=True)


if __name__=='__main__':run()
