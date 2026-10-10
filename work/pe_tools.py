import re, struct
from pathlib import Path
class PE:

    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        nt = self.u32(60)
        assert self.data[nt:nt + 4] == b'PE\x00\x00'
        self.timestamp = self.u32(nt + 8)
        optional = nt + 24
        assert self.u16(optional) == 523
        self.base = self.u64(optional + 24)
        self.size = self.u32(optional + 56)
        self.export_rva = self.u32(optional + 112)
        section_start = optional + self.u16(nt + 20)
        self.sections = []
        for i in range(self.u16(nt + 6)):
            p = section_start + i * 40
            self.sections.append(dict(name=self.data[p:p + 8].rstrip(b'\x00').decode(), vsize=self.u32(p + 8), rva=self.u32(p + 12), size=self.u32(p + 16), raw=self.u32(p + 20), flags=self.u32(p + 36)))

    def u16(self, p):
        return struct.unpack_from('<H', self.data, p)[0]

    def u32(self, p):
        return struct.unpack_from('<I', self.data, p)[0]

    def u64(self, p):
        return struct.unpack_from('<Q', self.data, p)[0]

    def offset(self, rva):
        for s in self.sections:
            if s['rva'] <= rva < s['rva'] + s['size']:
                return s['raw'] + rva - s['rva']
        raise ValueError(f'RVA {rva:x} not file-backed')

    def rva(self, offset):
        for s in self.sections:
            if s['raw'] <= offset < s['raw'] + s['size']:
                return s['rva'] + offset - s['raw']
        raise ValueError('offset not in section')

    def exports(self):
        if not self.export_rva:
            return {}
        p = self.offset(self.export_rva)
        functions = self.offset(self.u32(p + 28))
        names = self.offset(self.u32(p + 32))
        ordinals = self.offset(self.u32(p + 36))
        result = {}
        for i in range(self.u32(p + 24)):
            name_offset = self.offset(self.u32(names + i * 4))
            end = self.data.index(b'\x00', name_offset)
            result[self.data[name_offset:end].decode(errors='replace')] = self.u32(functions + self.u16(ordinals + i * 2) * 4)
        return result

    def find_pattern(self, pattern, section='.text'):
        tokens = pattern.replace('[', '').split()
        expression = b''.join((b'.' if '?' in t else re.escape(bytes([int(t, 16)])) for t in tokens))
        result = []
        for s in self.sections:
            if s['name'] != section:
                continue
            for m in re.finditer(expression, self.data[s['raw']:s['raw'] + s['size']], re.DOTALL):
                result.append(s['rva'] + m.start())
        return result

    def vtables(self, name):
        marker = ('.?AV' + name + '@@\x00').encode()
        pos = self.data.find(marker)
        if pos == -1:
            return []
        descriptor = self.rva(pos - 16)
        rdata = next((s for s in self.sections if s['name'] == '.rdata'))
        data = self.data[rdata['raw']:rdata['raw'] + rdata['size']]
        result = []
        start = 0
        while True:
            index = data.find(struct.pack('<I', descriptor), start)
            if index == -1:
                break
            start = index + 1
            col_offset = rdata['raw'] + index - 12
            if col_offset < rdata['raw']:
                continue
            col_rva = self.rva(col_offset)
            if self.u32(col_offset) != 1 or self.u32(col_offset + 4) != 0 or self.u32(col_offset + 20) != col_rva:
                continue
            pointer = struct.pack('<Q', self.base + col_rva)
            pointer_start = 0
            while True:
                vindex = data.find(pointer, pointer_start)
                if vindex == -1:
                    break
                pointer_start = vindex + 1
                table_rva = rdata['rva'] + vindex + 8
                if table_rva not in result:
                    result.append(table_rva)
        return result

def inspect(pe,rva,symbols):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    offset=pe.offset(rva);decoder=Cs(CS_ARCH_X86,CS_MODE_64)
    rows=[]
    for instruction in decoder.disasm(pe.data[offset:offset+768],pe.base+rva):
        rows.append({'rva':instruction.address-pe.base,'text':instruction.mnemonic+' '+instruction.op_str})
        if instruction.mnemonic=='ret' or len(rows)>=120:break
    return {'rva':rva,'prologue_hex':pe.data[offset:offset+24].hex(),'instructions':rows}
