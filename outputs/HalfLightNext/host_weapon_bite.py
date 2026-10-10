"""Short visual bites in DL2; never applies a force to Half Sword's ragdoll."""
import math

def compose(a, b):
    return tuple((sum((a[r * 4 + k] * b[k * 4 + c] for k in range(3))) + (a[r * 4 + 3] if c == 3 else 0) for r in range(3) for c in range(4)))

def camera_local(camera, world):
    return tuple((sum((camera[k * 4 + r] * (world[k * 4 + c] - (camera[k * 4 + 3] if c == 3 else 0)) for k in range(3))) for r in range(3) for c in range(4)))

class HostWeaponBite:

    def __init__(self):
        self.bites = {}
        self.sequence = {}

    def apply(self, bank, matrix, camera, events, shapes, tick, armed):
        world = compose(camera, matrix)
        for seq, entity, event_bank, region, point, normal, force, stick in events:
            if event_bank != bank or seq <= self.sequence.get(bank, 0):
                continue
            self.sequence[bank] = seq
            shape = next((s for s in shapes.get(entity, []) if s['region'] == region), None)
            if armed and stick > 0 and shape:
                self.bites[bank] = {'world': world, 'entity': entity, 'root': shape['root'], 'region': region, 'centre': shape['centre'], 'normal': normal, 'started': tick, 'until': tick + int(stick * 1000)}
        bite = self.bites.get(bank)
        if not bite:
            return matrix
        shape = next((s for s in shapes.get(bite['entity'], []) if s['region'] == bite['region'] and s['root'] == bite['root']), None)
        if not armed or tick >= bite['until'] or shape is None:
            self.bites.pop(bank, None)
            return matrix
        delta = tuple((shape['centre'][i] - bite['centre'][i] for i in range(3)))
        held = list(bite['world'])
        for i in range(3):
            held[i * 4 + 3] += delta[i]
        withdrawal = sum(((world[i * 4 + 3] - held[i * 4 + 3]) * bite['normal'][i] for i in range(3)))
        distance = sum(((held[i * 4 + 3] - camera[i * 4 + 3]) ** 2 for i in range(3)))
        if not all((math.isfinite(v) for v in held)) or distance > 9 or (tick - bite['started'] >= 150 and withdrawal < -0.12):
            self.bites.pop(bank, None)
            return matrix
        return camera_local(camera, held)
