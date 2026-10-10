"""Weapon-specific physical impact calibration shared by both hands."""
import struct
families={"Swords":0,"Daggers and short blades":1,"Axes":2,"Maces":3,"Polearms":4,"Staves":5,"Hafted weapons":6}

def combat_profile(p):
    # Physical feel needs a calibration knob; catalogue overrides share both hands.
    span=sum((a-b)**2 for a,b in zip(*p['cutting_segment_m']))**.5
    mass={'Swords':1.2,'Daggers and short blades':.45,'Axes':1.5,'Maces':1.7,'Polearms':2.2,'Staves':1.3,'Hafted weapons':1.8}[p['family']]
    values=p.get('combat',{})
    mass=values.get('mass_kg',mass*(1.25 if 'long' in p['id'] or 'two_hand' in p['id'] else 1))
    damage=values.get('damage_multiplier',1);stick=values.get('stick_seconds',.55 if p['family']=='Axes' else .5)
    assert .1<=mass<=8 and .1<=damage<=4 and 0<=stick<=.6 and span>0
    return struct.pack('<I3f',families[p['family']],mass,damage,stick)
