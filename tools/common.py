"""Shared helpers for the build scripts: romfs path, zstd with the game's dictionaries, SARC."""
import os, struct, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
HERE = ROOT


def romfs_path():
    p = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('OOT_ROMFS')
    if not p or not os.path.isdir(os.path.join(p, 'Pack')):
        sys.exit('usage: python %s <romfs folder>   (or set OOT_ROMFS)' % os.path.basename(sys.argv[0]))
    return p



def sarc(d):
    hl, = struct.unpack_from('<H', d, 4)
    dstart, = struct.unpack_from('<I', d, 0xC)
    n, = struct.unpack_from('<H', d, hl + 6)
    nodes = [struct.unpack_from('<IIII', d, hl + 0xC + 16 * i) for i in range(n)]
    names = hl + 0xC + 16 * n + 8
    out = {}
    for _, attr, s, e in nodes:
        no = names + (attr & 0xFFFF) * 4
        out[d[no:d.index(b'\0', no)].decode()] = d[dstart + s:dstart + e]
    return out


_DICTS = None


def _dicts():
    global _DICTS
    if _DICTS is None:
        import zstandard
        raw = open(os.path.join(romfs_path(), 'Pack', 'ZsDic.pack.zs'), 'rb').read()
        pack = sarc(zstandard.ZstdDecompressor().decompress(raw, max_output_size=1 << 26))
        _DICTS = [zstandard.ZstdCompressionDict(d) for n, d in sorted(pack.items()) if n.endswith('.zsdic')]
    return _DICTS


def decompress(raw):
    import zstandard
    if raw[:4] != b'\x28\xb5\x2f\xfd': return raw
    for dd in [None] + _dicts():
        try: return zstandard.ZstdDecompressor(dict_data=dd).decompress(raw, max_output_size=1 << 28)
        except Exception: pass
    raise ValueError('cannot decompress')
