"""Enemy, Link and weapon parameters from the actor packs -> actor_stats.json."""
from common import HERE, romfs_path, decompress
import json, os, re, struct, sys
from multiprocessing import Pool

from byml_lite import Byml
try:
    import mmh3
    def murmur3(b): return mmh3.hash(b, 0, signed=False)
except ImportError:
    from ootcore import murmur3

ROMFS = romfs_path()
SKIP_PREFIX = ('Land_', 'EftLoc_', 'Eftloc_', 'BGM_', 'SoundLocator_', 'CmnTex_', 'HrlField_')
KEEP_DIR = ('Life/', 'GameBalance/', 'GameParameter/', 'Player/', 'BSA/MovementParam/', 'Drop/',
            'Component/LifeParam/', 'Component/WeaponParam/', 'Component/DropParam/', 'Component/ShooterParam/',
            'Component/GameBalanceClientParam/', 'Component/PouchContentParam/', 'Component/BulletParam/')
SKIP_DIR = ('GameParameter/FoliageLikeBoneModifierParam/', 'GameParameter/GameClothParam/',
            'GameParameter/CctComponentPlayerRagdollParam/', 'GameParameter/InterestEmitterParam/',
            'GameParameter/RagdollReactionParam/', 'GameParameter/ElasticBodyParam/')
LOOSE = ('Life', 'GameBalance', 'GameParameter')
WORDS = """Sword Slash Bomb Explosion Arrow Fire Ice Light Hammer Boomerang Hookshot Longshot DekuStick DekuNut
Slingshot Nut Stick Magic Din Farore Nayru SpinAttack JumpAttack Spin Jump Normal Strong Weak Moderate Smash
Super None Default Invalid Shield Megaton Lsword Biggoron Giant Kokiri Master Bow Electric Thunder Water Punch
Kick Body Tackle Bite Claw Fist Blunt Pierce Stab Thrust Lightning Beam Laser Rock Wind Shock Shockwave Fall
Burn Poison Lava Freeze Frozen Elec Poe Ganon Rod Deku Bombchu Chu Spell Sun Song Reflect Hit Charge Guard
Rolling Roll Lower Upper Middle Small Big Medium Large Boss Mini Common Enemy Player Weapon Any All Melee Ranged
Physical Enemy Rank Class Level Low High Mid Head Tail Arm Leg Hand Foot Mirror Dark Silver Gold Light Fairy
Horse Cucco Cow Dog Fish Cut Stun Paralyze Bind Grab Throw Knock Back Down Up Left Right Front Rear Side Air
Ground Underwater Swim Ride Dash Run Walk Step Combo Finish First Second Third Last Final Thrown Rush Fly
Flying Dive Drop Bounce Lift Pull Push One Two Three Four Hand Handed Instant Kill Death Dead Damage Attack
Defense Power Type Weapon Ex Sp Special Glass Truth Hover Iron Boots Tunic Goron Zora Gerudo Sheikah""".split()
EXTRA_NAMES = ['GuardBreakStrong', 'HammerAttackEdge', 'PlayerChargeAttack']
TOKEN = re.compile(rb'[A-Za-z_][A-Za-z0-9_]{2,63}')


def norm(path):
    """'?Component/x.bgyml' or 'Work/Component/x.gyml' -> 'Component/x.bgyml'"""
    path = path.lstrip('?')
    if path.startswith('Work/'): path = path[5:]
    if path.endswith('.gyml'): path = path[:-5] + '.bgyml'
    return path


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


def wanted(path):
    return path.endswith('.bgyml') and path.startswith(KEEP_DIR) and not path.startswith(SKIP_DIR)


def load_pack(fn):
    """-> (actor name, {path: parsed}) with only the files we care about plus ActorParams."""
    name = fn[:-len('.pack.zs')]
    try: files = sarc(decompress(open(os.path.join(ROMFS, 'Pack', 'Actor', fn), 'rb').read()))
    except Exception: return name, {}, set()
    out, toks = {}, set()
    for p, d in files.items():
        toks.update(m.decode() for m in TOKEN.findall(d))
        if not (wanted(p) or p.startswith('Actor/') or p.startswith('GameParameter/GameParameterTable/')): continue
        try: out[p] = Byml(d).root
        except Exception: pass
    return name, out, toks


def merge(base, over):
    if not isinstance(base, dict) or not isinstance(over, dict): return over
    r = dict(base)
    for k, v in over.items(): r[k] = merge(r.get(k), v) if k in r else v
    return r


class Store:
    def __init__(self, files):
        self.files = files
        self.cache = {}

    def get(self, path, depth=0):
        path = norm(path)
        if path in self.cache: return self.cache[path]
        d = self.files.get(path)
        if not isinstance(d, dict) or depth > 12: return d
        if '$parent' in d:
            d = merge(self.get(d['$parent'], depth + 1) or {}, {k: v for k, v in d.items() if k != '$parent'})
        self.cache[path] = d
        return d


def strings(o, acc):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(k, str): acc.add(k)
            strings(v, acc)
    elif isinstance(o, list):
        for v in o: strings(v, acc)
    elif isinstance(o, str):
        acc.add(o)


def hashes(o, acc):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(k, int): acc.add(k)
            hashes(v, acc)
    elif isinstance(o, list):
        for v in o: hashes(v, acc)
    elif isinstance(o, int) and not isinstance(o, bool) and o > 0xFFFF:
        acc.add(o)


def hash_names(pool, want):
    """Name the hashes in want from pool strings and word combinations (only matches are kept)."""
    names = {}
    toks = set(WORDS)
    for s in pool:
        for part in re.split(r'[/._?]', s):
            if part: toks.add(part)
        for part in re.findall(r'[A-Z][a-z0-9]+|[A-Z]+(?![a-z])', s): toks.add(part)
    def cands():
        yield from pool
        yield from toks
        small = [t for t in toks if 2 <= len(t) <= 14 and t[:1].isupper()]
        for a in WORDS:
            for b in small:
                yield a + b
                yield b + a
    for c in cands():
        h = murmur3(c.encode())
        if h in want: names[h] = c
    return names


def decode(o, names):
    if isinstance(o, dict):
        return {(names.get(k, '#%d' % k) if isinstance(k, int) else k): decode(v, names) for k, v in o.items()}
    if isinstance(o, list): return [decode(v, names) for v in o]
    if isinstance(o, int) and not isinstance(o, bool) and o > 0xFFFF and o in names: return names[o]
    return o


def flatten(o, p='', out=None):
    out = {} if out is None else out
    if isinstance(o, dict):
        for k, v in o.items(): flatten(v, '%s.%s' % (p, k) if p else str(k), out)
    elif isinstance(o, list) and o and all(isinstance(v, (dict, list)) for v in o):
        for i, v in enumerate(o): flatten(v, '%s[%d]' % (p, i), out)
    else:
        out[p] = o
    return out


def category(name):
    if name.startswith('Player_'): return 'Link'
    if name.startswith('Enemy_'): return 'Bosses' if 'DungeonBoss' in name or 'MiddleBoss' in name else 'Enemies'
    if name.startswith(('Weapon_', 'Item_', 'Armor_')): return 'Weapons & items'
    return 'Other'


def collect(store, actor):
    """Follow the balance-related references from Actor/<actor>.engine__actor__ActorParam."""
    ap = store.get('Actor/%s.engine__actor__ActorParam.bgyml' % actor)
    if not isinstance(ap, dict): return {}
    found, todo = {}, list((ap.get('Components') or {}).values())
    while todo:
        ref = todo.pop()
        if not isinstance(ref, str) or not ref.endswith(('.bgyml', '.gyml')): continue
        path = norm(ref)
        if path in found: continue
        follow = path.startswith('GameParameter/GameParameterTable/') or wanted(path)
        if not follow: continue
        d = store.get(path)
        if not isinstance(d, dict): continue
        if not path.startswith('GameParameter/GameParameterTable/'): found[path] = d
        acc = set(); strings(d, acc)
        todo += [s for s in acc if s.endswith(('.bgyml', '.gyml'))]
    return found


def main():
    src = os.path.join(ROMFS, 'Pack', 'Actor')
    packs = [f for f in sorted(os.listdir(src)) if f.endswith('.pack.zs') and not f.startswith(SKIP_PREFIX)]
    files, actors, toks = {}, [], set(EXTRA_NAMES)
    with Pool() as pool:
        for name, fs, ts in pool.imap_unordered(load_pack, packs, chunksize=16):
            files.update(fs)
            actors.append(name)
            toks |= ts
    for top in LOOSE:
        for root, _, fns in os.walk(os.path.join(ROMFS, top)):
            for fn in fns:
                if not fn.endswith('.bgyml'): continue
                rel = os.path.relpath(os.path.join(root, fn), ROMFS).replace('\\', '/')
                try: files[rel] = Byml(open(os.path.join(root, fn), 'rb').read()).root
                except Exception: pass
    pool_s = set()
    for d in files.values(): strings(d, pool_s)
    pool_s |= set(actors) | toks
    want = set()
    for d in files.values(): hashes(d, want)
    names = hash_names(pool_s, want)
    store = Store(files)
    out = {}
    for a in sorted(actors):
        if '_Dictionary' in a: continue
        found = collect(store, a)
        if not any(k.startswith(('Life/LifeParameters/', 'GameBalance/AttackParam/', 'Component/WeaponParam/',
                                 'Player/PlayerGameParam/')) for k in found):
            continue
        out[a] = {'category': category(a),
                  'files': {k: flatten(decode(v, names)) for k, v in sorted(found.items())}}
    glob = {k: flatten(decode(store.get(k), names)) for k in sorted(files)
            if k.startswith(('Life/DamageGlobalParam/', 'GameParameter/EnemyGlobalParam/',
                             'GameParameter/KnockBackParam/', 'GameParameter/DropGlobalParam/'))}
    out['_Global'] = {'category': 'Other', 'files': glob}
    json.dump(out, open(os.path.join(HERE, 'actor_stats.json'), 'w', encoding='utf8'), ensure_ascii=False)
    cats = {}
    for v in out.values(): cats[v['category']] = cats.get(v['category'], 0) + 1
    print(len(out), 'actors', cats, len(names), 'hash names')


if __name__ == '__main__':
    main()
