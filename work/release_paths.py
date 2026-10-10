"""Local machine paths live in ignored configuration, never in source."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def local_path(kind, suffix=''):
    if kind == 'root':
        base = ROOT
    else:
        config = json.loads((ROOT / '.local/install.json').read_text(encoding='utf-8'))
        assert kind in ('dying_light', 'half_sword'), 'Unknown installation'
        base = Path(config[kind])
    candidate = (base / suffix).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise ValueError('Installation path escapes its root')
    return str(candidate)
