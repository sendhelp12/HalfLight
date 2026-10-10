"""Persistent, checksummed file transport for the guest's Lua-only reader.

No game APIs run here. An invalid header brackets each write; checksum and
matching footer reject torn reads. Consumers retain only their existing lease.
"""
import time, zlib
from pathlib import Path
from live_pose_transport import replace_packet
HEADER_BYTES = 39

class PacketStream:

    def __init__(self, destination, maximum, stream=None, compatibility=True):
        self.destination = Path(destination)
        self.maximum = maximum
        self.stream = stream if stream is not None else self.destination.with_suffix('.stream').open('w+b', buffering=0)
        self.compatibility = compatibility
        self.sequence = 0
        self.last_compatibility = 0

    def publish(self, text):
        payload = text.encode('ascii')
        if not 0 < len(payload) <= self.maximum:
            raise ValueError('Packet exceeds transport capacity')
        self.sequence += 1
        stamp = self.sequence
        header = f'HLS1,{stamp:016d},{len(payload):05d},{zlib.adler32(payload):010d}\n'.encode('ascii')
        assert len(header) == HEADER_BYTES
        footer = f'HLS1,{stamp:016d}\n'.encode('ascii')
        self.stream.seek(0)
        self.stream.write(b'!' * HEADER_BYTES)
        self.stream.write(payload + footer)
        self.stream.seek(0)
        self.stream.write(header)
        if self.compatibility and time.monotonic() - self.last_compatibility >= 0.25:
            temporary = self.destination.with_suffix('.tmp')
            temporary.write_text(text, encoding='ascii')
            replace_packet(temporary, self.destination)
            self.last_compatibility = time.monotonic()

    def close(self):
        self.stream.close()
