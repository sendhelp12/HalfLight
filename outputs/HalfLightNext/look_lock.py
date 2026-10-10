"""Input lease and held-click look anchor for the host-to-guest camera feed."""

class LookLock:

    def __init__(self, session):
        self.session = session
        self.sequence = 0
        self.deadline = 0
        self.expiry = 0
        self.enabled = False
        self.held = False
        self.anchor = None

    def update(self, controls, now, unix):
        try:
            seq = int(controls['seq'])
            expiry = int(controls['expires_at'])
            armed = controls['enabled']
            right = controls['right_guard']
            left = controls.get('left_guard', '0')
            held = '1' if right == '1' or left == '1' else '0'
            complete = controls['Session'] == self.session and seq > 0 and (str(seq) == controls['end_seq']) and (unix <= expiry <= unix + 1) and (armed in ('0', '1')) and (right in ('0', '1')) and (left in ('0', '1'))
        except (KeyError, ValueError, TypeError):
            complete = False
        if complete:
            if seq < self.sequence:
                self.enabled = False
                self.deadline = 0
            elif seq > self.sequence:
                self.sequence = seq
                self.deadline = now + 0.25
                self.expiry = expiry
                self.enabled = armed == '1'
                self.held = held == '1'
            if armed == '0':
                self.enabled = False
                self.deadline = 0
            if held == '0':
                self.held = False
                self.anchor = None
        if now >= self.deadline or unix > self.expiry:
            self.enabled = False
            self.held = False
            self.anchor = None
        return (self.enabled, self.enabled and self.held)

    def direction(self, pitch, yaw):
        if self.enabled and self.held:
            if self.anchor is None:
                self.anchor = (pitch, yaw)
            return self.anchor
        self.anchor = None
        return (pitch, yaw)
