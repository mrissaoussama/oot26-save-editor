"""Drop tables, which actors use them and where those actors are placed -> drops.json."""
from common import HERE, romfs_path, decompress, sarc
import glob, json, os
from multiprocessing import Pool

from byml_lite import Byml
from ootcore import murmur3

ROMFS = romfs_path()
SKIP_PREFIX = ('EftLoc_', 'Eftloc_', 'BGM_', 'SoundLocator_', 'CmnTex_')
NAMES = ['Rupee', 'Hp', 'Mp', 'Bomb', 'Bombchu', 'DekuNut', 'DekuStick', 'Fairy', 'Insect', 'Other', 'None',
         'Max', 'Normal', 'Zero', 'Random', 'MpMax', 'DekuSeedMax', 'ArrowMax', 'BombMax', 'BombchuMax',
         'DekuNutMax', 'DekuStickMax', 'FairyMax', 'Unlock', 'RedPotion', 'GreenPotion', 'BluePotion', 'HalfMilk',
         'MaxMilk', 'MostDepletedResource']
HASHES = {murmur3(n.encode()): n for n in NAMES}
HASHES[1113099761] = 'ArrowOrSeed'
PLACE_KEYS = ('Drop__DropTable', 'Drop__DropActor', 'Drop__DropActor_Substitute', 'Drop__CheckActor', 'DropViewActor',
              'ScrubDeku_ItemDropGameDataFlag', 'GetEventName', 'IsEnableRepeatOpen')


def stem(path):
    return os.path.basename(path).split('.')[0]


def norm(path):
    path = path.lstrip('?')
    if path.startswith('Work/'): path = path[5:]
    if path.endswith('.gyml'): path = path[:-5] + '.bgyml'
    return path


def decode(o):
    if isinstance(o, dict): return {k: decode(v) for k, v in o.items()}
    if isinstance(o, list): return [decode(v) for v in o]
    if isinstance(o, int) and not isinstance(o, bool) and o in HASHES: return HASHES[o]
    if isinstance(o, str) and o.startswith('Work/Actor/'): return stem(o)
    return o


def load(files, path, depth=0):
    d = files.get(norm(path))
    if not isinstance(d, dict) or depth > 12: return d
    if '$parent' in d:
        d = merge(load(files, d['$parent'], depth + 1) or {}, {k: v for k, v in d.items() if k != '$parent'})
    return d


def merge(base, over):
    if not isinstance(base, dict) or not isinstance(over, dict): return over
    r = dict(base)
    for k, v in over.items(): r[k] = merge(r.get(k), v) if k in r else v
    return r


def scan_pack(fn):
    name = fn[:-len('.pack.zs')]
    try: raw = sarc(decompress(open(os.path.join(ROMFS, 'Pack', 'Actor', fn), 'rb').read()))
    except Exception: return name, [], {}, {}
    if not any('DropParam' in p for p in raw): return name, [], {}, {}
    files = {}
    for p, d in raw.items():
        if p.startswith(('Actor/', 'Component/DropParam/', 'Drop/')) and p.endswith('.bgyml'):
            try: files[p] = Byml(d).root
            except Exception: pass
    ap = load(files, 'Actor/%s.engine__actor__ActorParam.bgyml' % name) or {}
    ref = (ap.get('Components') or {}).get('DropRef')
    dp = load(files, ref) if ref else None
    tlist = [norm(t) for t in (dp or {}).get('DropTableResourceList', [])]
    tables, subs = {}, {}
    for t in tlist:
        td = load(files, t)
        if not isinstance(td, dict): continue
        tables[stem(t)] = {'name': td.get('DropTableName', ''), 'subs': [stem(s) for s in td.get('SubTableList', [])],
                           **{k: v for k, v in td.items() if k not in ('DropTableName', 'SubTableList')}}
        for s in td.get('SubTableList', []):
            sd = load(files, s)
            if isinstance(sd, dict): subs[stem(s)] = decode(sd)
    return name, [stem(t) for t in tlist], tables, subs


def placements(drop_actors):
    out = []
    for f in sorted(glob.glob(os.path.join(ROMFS, 'Banc', '**', '*.bcett.byml.zs'), recursive=True)):
        try: root = Byml(decompress(open(f, 'rb').read())).root
        except Exception: continue
        if not isinstance(root, dict): continue
        scene = os.path.basename(f).split('.')[0]
        logic = {}
        for g in root.get('AiGroups', []):
            lg = os.path.basename(g.get('Logic', '')).replace('.ain', '')
            for r in g.get('References', []): logic.setdefault(r.get('Reference'), []).append(lg)
        for a in root.get('Actors', []):
            if not isinstance(a, dict): continue
            dyn = a.get('Dynamic') or {}
            params = {k: v for k, v in dyn.items() if k in PLACE_KEYS}
            actor = a.get('Gyaml', '')
            if not (actor in drop_actors or any(k.startswith('Drop') or 'ItemDrop' in k for k in params)): continue
            out.append({'scene': scene, 'actor': actor, 'id': a.get('Hash'),
                        'pos': [round(x, 1) for x in a.get('Translate', [])], 'params': params,
                        'logic': logic.get(a.get('Hash'), [])})
    return out


def global_param():
    for top in ('GameParameter',):
        for root, _, fns in os.walk(os.path.join(ROMFS, top)):
            for fn in fns:
                if fn.startswith('Default.game__drop__DropGlobalParam'):
                    return decode(Byml(open(os.path.join(root, fn), 'rb').read()).root)
    return {}


def foliage():
    try: raw = sarc(decompress(open(os.path.join(ROMFS, 'Pack', 'FoliageDropParam.pack.zs'), 'rb').read()))
    except Exception: return {}, {}, {}
    files = {p: Byml(d).root for p, d in raw.items() if p.endswith('.bgyml')}
    tables, subs, params = {}, {}, {}
    for p in files:
        if p.startswith('Drop/DropTable/'):
            td = load(files, p)
            tables[stem(p)] = {'name': td.get('DropTableName', ''), 'subs': [stem(s) for s in td.get('SubTableList', [])]}
        elif p.startswith('Drop/DropSubTable/'):
            subs[stem(p)] = decode(load(files, p))
        elif p.startswith('Game/FoliageDropParam/'):
            params[stem(p)] = decode(load(files, p))
    return tables, subs, params


def main():
    packs = [f for f in sorted(os.listdir(os.path.join(ROMFS, 'Pack', 'Actor')))
             if f.endswith('.pack.zs') and not f.startswith(SKIP_PREFIX)]
    actors, tables, subs = {}, {}, {}
    with Pool() as pool:
        for name, tl, ts, ss in pool.imap_unordered(scan_pack, packs, chunksize=16):
            if tl: actors[name] = tl
            tables.update(ts); subs.update(ss)
    ft, fs, fp = foliage()
    tables.update(ft); subs.update(fs)
    used = {a for a, tl in actors.items() if any(t != 'DropTable_None' for t in tl)}
    out = {'tables': tables, 'subs': subs, 'actors': actors, 'foliage': fp, 'global': global_param(),
           'placed': placements(used)}
    json.dump(out, open(os.path.join(HERE, 'drops.json'), 'w', encoding='utf8'), ensure_ascii=False, default=str)
    print(len(tables), 'drop tables,', len(actors), 'actors with drops,', len(out['placed']), 'placed')


if __name__ == '__main__':
    main()
