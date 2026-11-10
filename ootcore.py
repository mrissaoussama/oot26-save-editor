"""Ocarina of Time (Switch 2) GameData save format: read, write, diff.

Save layout (progress.sav / option.sav / caption.sav / account.sav):
  0x00 u32 magic 0x01020304
  0x04 u32 version
  0x08 u32 offset of the data area (end of the hash table)
  0x20 table of (u32 hash, u32 value) pairs. An entry with hash 0 starts a new
       type section; its value is the type index (see TYPES).
  Bool/Int/UInt/Float/Enum values are stored inline. Every other type stores an
  offset into the data area. Arrays start with a u32 element count.
  Bool64bitKey stores a zero-terminated list of the u64 keys that are set.
Names are murmur3_32(seed 0) of the flag name; struct members are "Struct.member".
"""
import json, os, re, shutil, struct

TYPES = ['Bool', 'BoolArray', 'Int', 'IntArray', 'Float', 'FloatArray', 'Enum', 'EnumArray',
         'Vector2', 'Vector2Array', 'Vector3', 'Vector3Array', 'String16', 'String16Array',
         'String32', 'String32Array', 'String64', 'String64Array', 'Binary', 'BinaryArray',
         'UInt', 'UIntArray', 'Int64', 'Int64Array', 'UInt64', 'UInt64Array', 'WString16',
         'WString16Array', 'WString32', 'WString32Array', 'WString64', 'WString64Array',
         'Bool64bitKey']
INLINE = {'Bool', 'Int', 'UInt', 'Float', 'Enum'}
NUM_ARRAYS = {'IntArray': 'i', 'UIntArray': 'I', 'FloatArray': 'f', 'Int64Array': 'q', 'UInt64Array': 'Q'}
EDITABLE = INLINE | {'Int64', 'UInt64', 'Vector3', 'String16', 'String32', 'String64',
                     'WString16', 'WString32', 'WString64', 'EnumArray'} | set(NUM_ARRAYS)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oot_flags_db.json')
DB = json.load(open(DB_PATH, encoding='utf8'))
NAMES = {int(k): v for k, v in DB['names'].items()}
BY_NAME = {v: k for k, v in NAMES.items()}
ENUMS = {int(k): {int(a): b for a, b in v.items()} for k, v in DB['enum'].items()}
ENUM_BY_LABEL = {h: {b: a for a, b in m.items()} for h, m in ENUMS.items()}
ACTOR = {int(k): v for k, v in DB['actor'].items()}
BKEY = DB.get('bkey', {})
# hash -> (type, save file index, reset type, default). Save file index: -1 = runtime only (never saved).
META = {int(k): tuple(v) for k, v in DB.get('meta', {}).items()}
SAVE_FILES = {0: 'progress.sav', 1: 'option.sav', 2: 'caption.sav', 3: 'account.sav'}


def storage(h, save=None):
    """Where a flag lives: 'file' (in this save), 'runtime', 'computed' or another file name."""
    if save is not None and h in save.entries: return 'file'
    m = META.get(h)
    if not m: return '?'
    if m[0] == 'BoolExp': return 'computed'
    if m[1] == -1: return 'runtime'
    return SAVE_FILES.get(m[1], 'file %d' % m[1])


def murmur3(data, seed=0):
    data = data.encode() if isinstance(data, str) else data
    c1, c2, h, n = 0xcc9e2d51, 0x1b873593, seed, len(data)
    rotl = lambda x, r: ((x << r) | (x >> (32 - r))) & 0xFFFFFFFF
    for i in range(0, n - n % 4, 4):
        k = int.from_bytes(data[i:i + 4], 'little')
        k = rotl(k * c1 & 0xFFFFFFFF, 15) * c2 & 0xFFFFFFFF
        h = (rotl(h ^ k, 13) * 5 + 0xe6546b64) & 0xFFFFFFFF
    tail = data[n - n % 4:]
    if tail:
        k = int.from_bytes(tail, 'little')
        h ^= rotl(k * c1 & 0xFFFFFFFF, 15) * c2 & 0xFFFFFFFF
    h ^= n
    h ^= h >> 16; h = h * 0x85ebca6b & 0xFFFFFFFF
    h ^= h >> 13; h = h * 0xc2b2ae35 & 0xFFFFFFFF
    return h ^ (h >> 16)


PARTIAL = {int(k): v for k, v in DB.get('partial', {}).items()}


def name(h):
    """Recovered name; '?xxxxxxxx' parts are hashes whose text is still unknown."""
    return NAMES.get(h) or PARTIAL.get(h) or '?%08x' % h


def caption_info(path):
    """Read a caption.sav: returns (jpeg bytes or None, dict of CaptionData fields)."""
    s = Save(path)
    jpeg, info = None, {}
    for h, (t, _) in s.entries.items():
        n = name(h)
        if n == 'CaptionData.ScreenShot':
            p = s.raw(h); size = struct.unpack_from('<I', s.d, p)[0]
            jpeg = bytes(s.d[p + 4:p + 4 + size])
        elif n.startswith('CaptionData.') and t != 'Binary':
            info[n[len('CaptionData.'):]] = s.get(h)
    return jpeg, info


def label(h):
    a = ACTOR.get(h)
    return name(h) + ('   [' + a + ']' if a else '')


def resolve(key):
    if key in BY_NAME: return BY_NAME[key]
    if re.fullmatch(r'\??(0x)?[0-9a-fA-F]{8}', key): return int(key.lstrip('?'), 16)
    return murmur3(key)


def enum_choices(h):
    return list(ENUM_BY_LABEL.get(h, {}))


def _str_size(t):
    m = re.match(r'(W?)String(\d+)', t)
    return int(m.group(2)) * (2 if m.group(1) else 1), bool(m.group(1))


class Save:
    def __init__(self, path):
        self.path = path
        self.d = bytearray(open(path, 'rb').read())
        magic, self.version, self.doff = struct.unpack_from('<III', self.d, 0)
        if magic != 0x01020304:
            raise ValueError('%s: not a GameData save (magic %08x)' % (path, magic))
        self.entries = {}
        o, t = 0x20, None
        while o < self.doff:
            h, v = struct.unpack_from('<II', self.d, o)
            if h == 0:
                t = TYPES[v] if v < len(TYPES) else 'type%d' % v
            else:
                self.entries[h] = (t, o)
            o += 8
        self.dirty = False

    def type(self, h):
        return self.entries[h][0]

    def raw(self, h):
        return struct.unpack_from('<I', self.d, self.entries[h][1] + 4)[0]

    def get(self, h):
        t = self.type(h)
        v = self.raw(h)
        d = self.d
        if t == 'Bool': return bool(v)
        if t == 'Int': return struct.unpack('<i', struct.pack('<I', v))[0]
        if t == 'UInt': return v
        if t == 'Float': return round(struct.unpack('<f', struct.pack('<I', v))[0], 4)
        if t == 'Enum': return ENUMS.get(h, {}).get(v) or NAMES.get(v) or '0x%08x' % v
        if t in ('Int64', 'UInt64'): return struct.unpack_from('<q' if t == 'Int64' else '<Q', d, v)[0]
        if t == 'Vector3': return [round(x, 3) for x in struct.unpack_from('<3f', d, v)]
        if t == 'Bool64bitKey':
            out, o = [], v
            while True:
                k = struct.unpack_from('<Q', d, o)[0]; o += 8
                if not k: return out
                out.append('0x%x' % k + (' [' + BKEY['0x%x' % k] + ']' if '0x%x' % k in BKEY else ''))
        if t.startswith('String') or t.startswith('WString'):
            size, wide = _str_size(t)
            dec = (lambda b: b.decode('utf-16le', 'replace').split('\0')[0]) if wide else \
                  (lambda b: b.split(b'\0')[0].decode('utf8', 'replace'))
            if t.endswith('Array'):
                n = struct.unpack_from('<I', d, v)[0]
                return [dec(bytes(d[v + 4 + i * size:v + 4 + (i + 1) * size])) for i in range(n)]
            return dec(bytes(d[v:v + size]))
        n = struct.unpack_from('<I', d, v)[0]
        if t in NUM_ARRAYS:
            vals = list(struct.unpack_from('<%d%s' % (n, NUM_ARRAYS[t]), d, v + 4))
            return [round(x, 3) for x in vals] if t == 'FloatArray' else vals
        if t == 'EnumArray':
            return [ENUMS.get(h, {}).get(x, '0x%08x' % x) for x in struct.unpack_from('<%dI' % n, d, v + 4)]
        if t == 'BoolArray':
            return '<BoolArray %d>' % n
        return '<%s %d bytes>' % (t, n)

    def _enum_value(self, h, text):
        labels = ENUM_BY_LABEL.get(h, {})
        if text in labels: return labels[text]
        if labels: raise ValueError('unknown value %r; choices: %s' % (text, ', '.join(labels)))
        if re.fullmatch(r'0x[0-9a-fA-F]+', text): return int(text, 16)
        return murmur3(text)

    def set(self, h, value):
        """value may be a python value or text (as typed by a user)."""
        t, o = self.entries[h]
        if t not in EDITABLE:
            raise ValueError('editing %s values is not supported' % t)
        if isinstance(value, str) and t in set(NUM_ARRAYS) | {'Vector3', 'EnumArray'}:
            value = json.loads(value)
        if t == 'Bool':
            v = 1 if (value is True or str(value).lower() in ('1', 'true', 'on', 'yes')) else 0
        elif t == 'Int':
            v = struct.unpack('<I', struct.pack('<i', int(str(value), 0)))[0]
        elif t == 'UInt':
            v = int(str(value), 0) & 0xFFFFFFFF
        elif t == 'Float':
            v = struct.unpack('<I', struct.pack('<f', float(value)))[0]
        elif t == 'Enum':
            v = self._enum_value(h, str(value))
        else:
            v = None
            p = self.raw(h)
            if t in ('Int64', 'UInt64'):
                struct.pack_into('<q' if t == 'Int64' else '<Q', self.d, p, int(str(value), 0))
            elif t == 'Vector3':
                if len(value) != 3: raise ValueError('Vector3 needs 3 numbers')
                struct.pack_into('<3f', self.d, p, *map(float, value))
            elif t in NUM_ARRAYS or t == 'EnumArray':
                n = struct.unpack_from('<I', self.d, p)[0]
                if len(value) != n: raise ValueError('array must keep its %d elements' % n)
                if t == 'EnumArray':
                    value = [self._enum_value(h, str(x)) for x in value]
                    fmt = 'I'
                else:
                    fmt = NUM_ARRAYS[t]
                    value = [float(x) if fmt == 'f' else int(x) for x in value]
                struct.pack_into('<%d%s' % (n, fmt), self.d, p + 4, *value)
            else:
                size, wide = _str_size(t)
                b = str(value).encode('utf-16le' if wide else 'utf8')
                if len(b) >= size: raise ValueError('text too long (max %d bytes)' % (size - 1))
                self.d[p:p + size] = b + b'\0' * (size - len(b))
        if v is not None:
            struct.pack_into('<I', self.d, o + 4, v)
        self.dirty = True

    def bkey_flag(self):
        return next((h for h, (t, _) in self.entries.items() if t == 'Bool64bitKey'), None)

    def bkeys(self):
        h = self.bkey_flag()
        if h is None: return set()
        out, o = set(), self.raw(h)
        while True:
            k = struct.unpack_from('<Q', self.d, o)[0]; o += 8
            if not k: return out
            out.add(k)

    def set_bkey(self, key, on):
        """Add or remove one per-actor key. The list is kept sorted and must end the file."""
        h = self.bkey_flag()
        if h is None: raise ValueError('this save has no Bool64bitKey list')
        keys = self.bkeys()
        start = self.raw(h)
        if start + 8 * (len(keys) + 1) != len(self.d):
            raise ValueError('Bool64bitKey list is not at the end of the file; refusing to resize')
        keys.add(key) if on else keys.discard(key)
        self.d[start:] = b''.join(struct.pack('<Q', k) for k in sorted(keys)) + b'\0' * 8
        self.dirty = True

    def write(self, path=None):
        path = path or self.path
        bak = path + '.bak'
        if os.path.exists(path) and not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'wb') as f:
            f.write(self.d)
        self.path = path
        self.dirty = False


def diff(a, b):
    """Yield (hash, type, value_a, value_b) for flags that differ."""
    for h in sorted(set(a.entries) | set(b.entries), key=name):
        va = a.get(h) if h in a.entries else '<absent>'
        vb = b.get(h) if h in b.entries else '<absent>'
        if va != vb:
            yield h, (a.entries.get(h) or b.entries[h])[0], va, vb
