"""Validated local weapon geometry; owned asset buffers remain private."""
import json, math, re
from functools import lru_cache
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

def validate(profile):
    assert re.fullmatch('[a-z][a-z0-9_]{0,63}', profile['id'])
    assert re.fullmatch('halflight_[a-z0-9_]+\\.msh', profile['native_mesh'])
    assert re.fullmatch('[A-Za-z0-9_]+_C', profile['actor_class']) and re.fullmatch('[A-Za-z0-9_ ]+', profile['component'])
    assert 0 <= profile['pose_offset_cm'] <= 30
    assert profile['source_parts'] and all((re.fullmatch('[A-Za-z0-9_ ]+', k) and v.startswith('/Game/') and (not any((c in v for c in '\r\n='))) for k, v in profile['source_parts'].items()))
    assert profile['component'] in profile['source_parts']
    assert len(profile.get('source_scale', [1, 1, 1])) == 3 and all((0.05 <= v <= 10 for v in profile.get('source_scale', [1, 1, 1])))
    assert profile.get('damage_type', 1) in (1, 18)
    assert profile.get('family', 'Axes') in ('Swords', 'Daggers and short blades', 'Axes', 'Hafted weapons', 'Maces', 'Polearms', 'Staves')
    scales = profile.get('source_part_scales', {})
    assert all((k in profile['source_parts'] and len(v) == 3 and all((math.isfinite(n) and 0.05 <= n <= 10 for n in v)) for k, v in scales.items()))
    assert len(profile['cutting_segment_m']) == 2 and all((len(p) == 3 for p in profile['cutting_segment_m']))
    numbers = [*profile['grip_centre_m'], profile['grip_radius_m'], profile['blade_radius_m'], *(v for p in profile['cutting_segment_m'] for v in p)]
    assert all((math.isfinite(v) and abs(v) < 4 for v in numbers))
    assert 0.008 < profile['grip_radius_m'] < 0.025 and 0 <= profile['blade_radius_m'] < 0.1
    return profile

@lru_cache(maxsize=1)
def catalog():
    path = ROOT / '.local/catalog.json'
    data = json.loads(path.read_text())
    assert data['version'] == 1 and 1 <= len(data['weapons']) <= 32
    profiles = [validate(p) for p in data['weapons']]
    for p in profiles:
        geometry = (ROOT / p['geometry_path']).resolve()
        assert geometry.is_relative_to(ROOT / 'work/owned-assets') and geometry.is_file()
        assert math.isfinite(p['geometry_offset_cm']) and abs(p['geometry_offset_cm']) <= 30
        assert p['grip_shape'] in ('cylinder', 'mesh') and isinstance(p['label'], str) and (0 < len(p['label']) <= 80)
    assert len({p['id'] for p in profiles}) == len(profiles) and len({p['native_mesh'] for p in profiles}) == len(profiles)
    return profiles

def selected():
    path = ROOT / 'work/lab/selected-weapon.json'
    return validate(json.loads(path.read_text()) if path.exists() else dict(catalog()[0]))
