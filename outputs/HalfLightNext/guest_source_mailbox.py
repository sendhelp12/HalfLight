"""Pagefile-backed latest guest row, using the existing HLS1 commit format."""
import mmap,zlib
from pathlib import Path
from packet_stream import HEADER_BYTES

def open_mailbox(session,write=False):
    assert len(session)==16 and all(c in '0123456789abcdef' for c in session)
    # Readers can arrive first. The shared object must permit the producer's
    # writable view regardless of which process creates it; consumers only read.
    return mmap.mmap(-1,4096,tagname='Local\\HalfLightGuest-'+session,
                     access=mmap.ACCESS_WRITE)

def read_mailbox(view):
    raw=view[:];header=raw[:HEADER_BYTES]
    try:
        magic,sequence,length,checksum=header.decode('ascii').strip().split(',')
        length=int(length);sequence=int(sequence);checksum=int(checksum)
        if magic!='HLS1' or sequence<=0 or not 0<length<=1024:return
        payload=raw[HEADER_BYTES:HEADER_BYTES+length]
        footer=f'HLS1,{sequence:016d}\n'.encode('ascii')
        if raw[HEADER_BYTES+length:HEADER_BYTES+length+22]!=footer or zlib.adler32(payload)!=checksum:return
        return payload.decode('ascii')
    except (ValueError,UnicodeError):return

class GuestPoseRows:
    def __init__(self,active):
        self.view=open_mailbox(active['source_mailbox']) if active.get('source_mailbox') else None
        self.path=Path(active['source_path']);self.offset=0;self.pending=''
    def read(self):
        if self.view is not None:
            row=read_mailbox(self.view);return [row] if row else []
        with self.path.open('rb') as stream:
            stream.seek(self.offset);chunk=stream.read();self.offset=stream.tell()
        self.pending+=chunk.decode('ascii');lines=self.pending.split('\n');self.pending=lines.pop();return lines
    def close(self):
        if self.view is not None:self.view.close();self.view=None
