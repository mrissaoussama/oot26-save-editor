"""Pull printable strings out of the game executable (exefs/main, NSO) to name murmur3 enum hashes."""
import os, re, struct, sys

import lz4.block


def nso_ro(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'NSO0'
    flags, = struct.unpack_from('<I', d, 0xC)
    out = b''
    for i in (1, 2):
        foff, moff, size = struct.unpack_from('<III', d, 0x10 + 0x10 * i)
        csize, = struct.unpack_from('<I', d, 0x60 + 4 * i)
        seg = d[foff:foff + csize]
        if flags & (1 << i): seg = lz4.block.decompress(seg, uncompressed_size=size)
        out += seg
    return out


def strings(path):
    data = nso_ro(path)
    return set(m.decode() for m in re.findall(rb'[A-Za-z_][A-Za-z0-9_]{2,63}', data))


if __name__ == '__main__':
    if len(sys.argv) < 2: sys.exit('usage: python exe_strings.py <exefs/main>')
    s = strings(sys.argv[1])
    print(len(s))
