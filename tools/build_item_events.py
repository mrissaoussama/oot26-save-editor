"""Events that give items or change the map -> ITEM_EVENTS.md (needs events/)."""
from common import HERE
import glob, os, re, collections

ITEM = r'((?:Item|Weapon|Armor|Obj_Heart|Pouch)_[A-Za-z0-9_]+)'
GIVE = [re.compile(r'(?:GetInEvent|GetPouchContent|AddOrRemovePouchContent|Dm_SY_Get|SetForGetWindow|CreateShowItem)[^\n]*?(?:ActorName|Actor)=' + ITEM),
        re.compile(r'GameDataName=IsGet\.' + ITEM + r'[^\n]*Value=True|Value=True[^\n]*GameDataName=IsGet\.' + ITEM)]
WARP = re.compile(r'EventReserveBancChange\(([^\n]*)\)')
SKIP_ITEMS = {'Item_Dummy'}


def words(s):
    return {w.lower() for w in re.findall(r'[A-Z][a-z]+|[a-z]+|[0-9]+', s) if len(w) > 2}


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(HERE, 'events', '*.txt'))):
        ev = os.path.basename(f)[:-4]
        text = open(f, encoding='utf8', errors='replace').read()
        items = collections.OrderedDict()
        for rx in GIVE:
            for m in rx.finditer(text):
                it = next(g for g in m.groups() if g)
                if it not in SKIP_ITEMS and not it.startswith('Pouch_Range'): items[it] = 1
        warps = []
        for m in WARP.finditer(text):
            args = dict(re.findall(r'(\w+)=([^,)]*)', m.group(1)))
            if args.get('NextBanc'):
                w = '%s @ %s' % (args['NextBanc'], args.get('NextStartPos', '?'))
                if args.get('IsItemWarp') == 'True': w += ' (item warp)'
                if w not in warps: warps.append(w)
        if items or warps:
            ew = words(ev)
            side = [it for it in items if not (words(it.split('_', 1)[-1]) & ew)]
            rows.append((ev, list(items), warps, side))
    out = ['# Events that give items or change the map', '',
           'Built by build_item_events.py from events/*.txt. **side** = the event name does not mention the item, '
           'so the item comes with another cutscene (good to know when skipping or warping past it).', '']
    out += ['## Items given as part of another cutscene (side)', '', '| event | items | map change |', '|---|---|---|']
    for ev, items, warps, side in rows:
        if side: out.append('| `%s` | %s | %s |' % (ev, ', '.join('`%s`' % i for i in side), '<br>'.join(warps) or ''))
    out += ['', '## Every event that gives an item', '', '| event | items |', '|---|---|']
    for ev, items, warps, side in rows:
        if items: out.append('| `%s` | %s |' % (ev, ', '.join('`%s`' % i for i in items)))
    out += ['', '## Every event that changes the map', '', '| event | to (map @ spawn point) |', '|---|---|']
    for ev, items, warps, side in rows:
        if warps: out.append('| `%s` | %s |' % (ev, '<br>'.join(warps)))
    open(os.path.join(HERE, 'ITEM_EVENTS.md'), 'w', encoding='utf8').write('\n'.join(out) + '\n')
    print('%d events with items or warps, %d with side items' % (len(rows), sum(1 for r in rows if r[3])))


if __name__ == '__main__':
    main()
