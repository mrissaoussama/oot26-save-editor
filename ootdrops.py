"""Readable drop data from drops.json: what drops an item, where, and under which conditions."""
import json, os, re
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ('Items', 'Sources', 'Drop tables', 'Maps')
_cache = {}
LOCK = ('Items Link cannot use yet (bombs, arrows, seeds, magic...) drop as a Green Rupee until their unlock flag is set; '
        'open an item for its flag.')

TYPE_ACTOR = {'Hp': 'Obj_Heart', 'Mp': 'Obj_MagicJar_Small', 'Bomb': 'Obj_Bomb', 'Bombchu': 'Obj_Bombchu',
              'DekuNut': 'Obj_DekuNut', 'DekuStick': 'Obj_DekuStick', 'Fairy': 'Obj_Fairy', 'Insect': 'Animal_Insect',
              'Rupee': 'Obj_Rupee_Green'}
TYPE_NAME = {'ArrowOrSeed': 'Arrows (adult) / Deku Seeds (child)',
             'MostDepletedResource': 'whatever Link is lowest on'}
ITEM_NAMES = {'Heart': 'Recovery Heart', 'MagicJar_Small': 'Small Magic Jar', 'MagicJar_Large': 'Large Magic Jar',
              'ArrowBundle_Small': 'Arrows (small bundle)', 'ArrowBundle_Medium': 'Arrows (medium bundle)',
              'ArrowBundle_Large': 'Arrows (large bundle)', 'Insect': 'Bug', 'BombBundle_Small': 'Bombs (small bundle)',
              'Heart_Container': 'Heart Container', 'Heart_Piece': 'Piece of Heart', 'Dungeon_Compass': 'Compass',
              'Dungeon_Map': 'Dungeon Map', 'Dungeon_SmallKey': 'Small Key', 'Dungeon_BossKey': 'Boss Key',
              'Range_Bow': 'Fairy Bow', 'Range_SlingShot': 'Fairy Slingshot', 'Glass_Truth': 'Lens of Truth',
              'Arrow_Ice': 'Ice Arrows', 'Arrow_Fire': 'Fire Arrows', 'Arrow_Light': 'Light Arrows',
              'Token_Gold': 'Gold Skulltula Token', 'Hammer': 'Megaton Hammer'}
NOUN_FIRST = ('Rupee', 'Shield', 'Sword', 'Tunic', 'Boots', 'Gauntlet', 'Medal', 'Melody', 'Stone')
SOURCE_NAMES = [(r'TBox', 'Chest'), (r'Pot_|^Pot$', 'Pot'), (r'FlyingPot', 'Flying Pot'), (r'LiftRock', 'Liftable rock'),
                (r'BrokenRock', 'Breakable rock'), (r'BrokenBox', 'Crate'), (r'Plant_Grass|Plant_A_02', 'Grass / bush'),
                (r'WallCrack', 'Bombable wall'), (r'SpawnDropsPeriodically', 'Periodic drop spawner'),
                (r'Beehive', 'Beehive'), (r'PalmFruit', 'Palm fruit'), (r'Tree', 'Tree'), (r'Rubble', 'Rubble'),
                (r'CowBone', 'Cow skull'), (r'IronKnuckle_Pillar', 'Iron Knuckle pillar'), (r'CrackWall', 'Cracked wall')]
AGE = {'Child': 'child', 'Adult': 'adult'}


def data():
    if not _cache:
        p = os.path.join(HERE, 'drops.json')
        _cache['d'] = json.load(open(p, encoding='utf8')) if os.path.exists(p) else {}
        if _cache['d']: _index()
    return _cache['d']


def available():
    return bool(data())


def words(s):
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', s)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    return s.replace('_', ' ').strip()


def item_name(actor):
    """Obj_Rupee_Blue / TBox_Rupee_Blue -> Blue Rupee."""
    if actor in TYPE_NAME: return TYPE_NAME[actor]
    base = re.sub(r'^(TBox|Item|Obj|Animal|Tbox)_', '', actor)
    if base in ITEM_NAMES: return ITEM_NAMES[base]
    parts = base.split('_')
    if len(parts) == 2 and parts[0] in NOUN_FIRST: parts = [parts[1], parts[0]]
    return words(' '.join(parts))


def source_name(actor):
    if actor.startswith('Enemy_'):
        return words(actor[6:].replace('DungeonBoss_', '').replace('MiddleBoss_', '')) + ' (enemy)'
    for rx, n in SOURCE_NAMES:
        if re.search(rx, actor): return n
    return words(re.sub(r'^(Obj|Land|Animal|Weapon)_', '', actor))


def map_key(scene):
    return re.sub(r'_(Static|Dynamic)$', '', scene)


def scene_name(scene):
    parts = scene.split('_')
    base = parts[0]
    age = next((AGE[p] for p in parts[1:] if p in AGE), '')
    return words(base) + (' (%s)' % age if age else '')


def _index():
    d = _cache['d']
    alias = {}
    for k, t in d['tables'].items():
        alias[k] = k
        if t.get('name'): alias.setdefault(t['name'], k)
    _cache['alias'] = alias
    by_item = defaultdict(list)     # item label -> [(table, chance text)]
    for k, t in d['tables'].items():
        for e in entries(k):
            by_item[e['item']].append((k, e))
    _cache['by_item'] = by_item
    fixed = defaultdict(list)       # item label -> placements that drop it directly
    for p in d['placed']:
        for key in ('Drop__DropActor', 'Drop__DropActor_Substitute'):
            a = p['params'].get(key)
            if a: fixed[item_name(a)].append(p)
    _cache['fixed'] = fixed
    by_table = defaultdict(list)
    for p in d['placed']:
        t = table_of(p)
        if t: by_table[t].append(p)
    _cache['by_table'] = by_table
    labels = {}
    for it in set(by_item) | set(fixed): labels[it] = ('Items', it)
    for a in set(d['actors']) | {p['actor'] for p in d['placed']}:
        labels['%s  [%s]' % (source_name(a), a)] = ('Sources', a)
    for k in d['tables']: labels[k] = ('Drop tables', k)
    for s in {map_key(p['scene']) for p in d['placed']}: labels['%s  [%s]' % (scene_name(s), s)] = ('Maps', s)
    _cache['by_id'] = {str(p['id']): p for p in d['placed']}
    _cache['labels'] = labels


def entries(table):
    """Readable rows of a drop table: [{item, chance, count, note}]."""
    d = data()
    out = []
    for sk in d['tables'].get(table, {}).get('subs', []):
        s = d['subs'].get(sk, {})
        items = s.get('Items') or []
        if isinstance(items, list) and items:
            total = sum(i.get('DropProbability', 0) for i in items)
            for i in items:
                w = i.get('DropProbability', 0)
                out.append({'item': _label(i), 'count': i.get('DropCreateCount', 1),
                            'chance': ('%d%%' % round(100.0 * w / total)) if w and total else '0% (boost only)',
                            'note': _note(i)})
        if s.get('LotteryType') == 'Max':
            for key, rank in (('Items_Max_FirstCandidate', 'slot 1'), ('Items_Max_SecondCandidate', 'slot 2'),
                              ('Items_Max_ThirdCandidate', 'slot 3')):
                c = _sub_list(s, key)
                for i in c:
                    others = [_label(x) for x in c if x is not i]
                    out.append({'item': _label(i), 'count': i.get('DropCreateCount', 1), 'chance': rank,
                                'note': ('slot shared with ' + ', '.join(others)) if others else ''})
    return out


def _sub_list(s, key):
    if key in s:
        v = s[key]
        return [v] if isinstance(v, dict) else [x for x in v if isinstance(x, dict)]
    rows = {}
    for k, v in s.items():
        m = re.match(r'%s(?:\[(\d+)\])?\.(\w+)$' % key, k)
        if m: rows.setdefault(int(m.group(1) or 0), {})[m.group(2)] = v
    return [rows[i] for i in sorted(rows)]


def _label(i):
    a = i.get('DropActorName') or TYPE_ACTOR.get(i.get('Type'), '') or str(i.get('Type'))
    if isinstance(i.get('Type'), int): a = 'unnamed type #%d' % i['Type']
    return item_name(a)


def _note(i):
    n = []
    if i.get('MostDepletedResource'): n.append('among ' + ', '.join(item_name(TYPE_ACTOR.get(x, x)) for x in i['MostDepletedResource']))
    if i.get('IsReplace') is False: n.append('never replaced')
    if i.get('BadLuckValueRate', 1) not in (1, 1.0): n.append('bad-luck rate x%s' % i['BadLuckValueRate'])
    return '; '.join(n)


def table_of(p):
    """Drop table a placed actor uses: its Drop__DropTable parameter, else the actor's default."""
    d = data()
    t = p['params'].get('Drop__DropTable')
    if t == 'None': return None
    if t: return _cache['alias'].get(t, t)
    tl = d['actors'].get(p['actor'])
    return tl[0] if tl else None


def search(q, k='Items', limit=5000):
    if not available(): return []
    ws = q.lower().split()
    return sorted(n for n, (kind, raw) in _cache['labels'].items()
                  if (k == kind) and all(w in n.lower() for w in ws))[:limit]


def resolve(q):
    data()
    q = q.strip()
    if q in _cache['labels']: return _cache['labels'][q]
    m = re.search(r'\[([^\]]+)\]$', q)
    if m: q = m.group(1)
    d = data()
    if q in d['tables'] or q in _cache['alias']: return 'Drop tables', _cache['alias'].get(q, q)
    if q in d['actors'] or any(p['actor'] == q for p in d['placed']):
        if item_name(q) in _cache['fixed'] or item_name(q) in _cache['by_item']:
            if not q.startswith(('Enemy_',)) and q not in d['actors']: return 'Items', item_name(q)
        return 'Sources', q
    if any(map_key(p['scene']) == map_key(q) for p in d['placed']): return 'Maps', map_key(q)
    if q.startswith('IsTreasureBoxOpen.') and q.split('.', 1)[1] in _cache['by_id']: return 'Chest', q.split('.', 1)[1]
    if item_name(q) in _cache['by_item'] or item_name(q) in _cache['fixed']: return 'Items', item_name(q)
    for lab, (kind, raw) in _cache['labels'].items():
        if kind == 'Items' and lab.lower() == q.lower(): return kind, raw
    return None, q


def where(p):
    x, y, z = (p['pos'] + [0, 0, 0])[:3]
    return '%s  at (%.1f, %.1f, %.1f)' % (scene_name(p['scene']), x, y, z)


def conditions(p):
    """Lines explaining when a placed actor gives its drop."""
    out = []
    pr = p['params']
    if 'TBox' in p['actor']:
        out.append('opened flag: IsTreasureBoxOpen.%s' % p['id'])
    if pr.get('GetEventName'): out.append('event when opened: %s' % pr['GetEventName'])
    if pr.get('Drop__CheckActor'):
        out.append('if Link already has %s (%s), gives %s (%s) instead' % (
            item_name(pr['Drop__CheckActor']), pr['Drop__CheckActor'],
            item_name(pr.get('Drop__DropActor_Substitute', '?')), pr.get('Drop__DropActor_Substitute', '?')))
    if pr.get('DropViewActor'): out.append('shows %s inside' % pr['DropViewActor'])
    if pr.get('IsEnableRepeatOpen'): out.append('can be opened again')
    if pr.get('ScrubDeku_ItemDropGameDataFlag'): out.append('drops once, flag: %s' % pr['ScrubDeku_ItemDropGameDataFlag'])
    out += logic_lines(p)
    return out


def logic_lines(p, limit=4):
    try:
        import ootrefs, ootplain
        rules = ootrefs.data()['rules']
    except Exception:
        return []
    out = []
    fam = re.sub(r'_[A-Z]_\d+.*$|_\d+$', '', p['actor'].replace('Obj_', ''))
    for m in p['logic']:
        hits = [r for r in rules if r['module'] == m and r.get('cond') and
                (fam.lower() in r['effect'].lower() or 'tbox' in r['effect'].lower() and 'TBox' in p['actor'])]
        seen = []
        for r in hits:
            c = ootplain.cond_short(r['cond'])
            line = 'logic: %s  WHEN  %s' % (r['effect'], c if len(c) < 260 else c[:260] + ' …')
            if line not in seen: seen.append(line)
        out += seen[:limit]
        if not hits: out.append('scene logic module: %s' % m)
    return out


def global_rules(item):
    """Unlock flags and replacement rules from the global drop settings that affect this item."""
    g = data()['global'].get('DropLotteryMasterData', {})
    names = {item}
    if item == TYPE_NAME['ArrowOrSeed']: names |= {item_name('Obj_ArrowBundle_Small'), item_name('Obj_DekuSeed')}
    out = []
    for u in g.get('DropUnlockCondition', []):
        if item_name(u.get('Actor', '')) in names:
            n = item_name(u.get('Actor', ''))
            out.append('%slocked until flag %s is true' % ('' if n == item else n + ': ', u.get('GameDataName')))
    for r in g.get('ReplaceSetting', []):
        tgt = item_name(r.get('TargetActor', ''))
        if tgt not in names: continue
        rep = ', '.join('%s (%s%%)' % (item_name(x.get('ReplaceActor', '')), x.get('Probability', 100))
                        for x in r.get('ReplaceActor', []))
        c = r.get('Condition', '')
        why = {'Unlock': 'while locked', 'MpMax': 'when magic is full or not learned',
               'FairyMax': 'when no empty bottle / fairies full'}.get(c, 'when %ss are full' % words(str(c)[:-3]).lower() if str(c).endswith('Max') else 'when %s' % words(str(c)).lower())
        if isinstance(c, int): why = 'when condition #%d' % c
        if not c: why = '(no condition in the data)'
        out.append('%sbecomes %s %s' % ('' if tgt == item else tgt + ': ', rep.replace(' (100%)', ''), why))
    return out


def low_boost(item):
    g = data()['global'].get('DropLotteryMasterData', {})
    rev = {item_name(TYPE_ACTOR.get(k, k)): k for k in list(TYPE_ACTOR) + ['ArrowOrSeed']}
    t = rev.get(item)
    if not t: return []
    from ootcore import murmur3
    out = []
    for key in ('DepletedInfoData1', 'DepletedInfoData2'):
        tier = g.get(key) or {}
        di = tier.get(t) or tier.get(str(murmur3(t.encode())))
        if not di or not di.get('AddProbability') or not di.get('DepletedValueList'): continue
        lv = ' / '.join('%s of %s' % (x.get('NowNum'), x.get('MaxNum')) for x in di['DepletedValueList'])
        out.append('+%s%% when Link has at most %s' % (di['AddProbability'], lv))
    return out


def report(q, raw=False):
    if not available(): return 'Drop data not built.'
    kind, key = resolve(q)
    if kind == 'Items': return item_report(key, raw)
    if kind == 'Sources': return source_report(key, raw)
    if kind == 'Drop tables': return table_report(key, raw)
    if kind == 'Maps': return map_report(key, raw)
    if kind == 'Chest':
        p = _cache['by_id'][key]
        out = ['Chest  [%s]' % p['actor'], '', 'CONTAINS: %s  [%s]' % (item_name(p['params'].get('Drop__DropActor', '?')),
               p['params'].get('Drop__DropActor', '?')), 'WHERE: %s' % where(p), '']
        same = [x for x in data()['placed'] if str(x['id']) == key and x is not p]
        if same: out += ['ALSO IN: ' + ', '.join(scene_name(x['scene']) for x in same), '']
        out += ['CONDITIONS:'] + ['  ' + c for c in conditions(p)]
        return '\n'.join(out)
    try:
        import ootrefs
        if ootrefs.available(): return ootrefs.report(q, raw)
    except Exception: pass
    return 'Nothing found for %s.' % q


def _group(places, limit=60):
    by = defaultdict(list)
    for p in places: by[map_key(p['scene'])].append(p)
    return sorted(by.items(), key=lambda kv: scene_name(kv[0]))[:limit]


def _names(actors, limit=10):
    """Actors grouped by readable name: Pot (4 variants), Crate (3 variants), Amos (enemy)."""
    by = defaultdict(list)
    for a in actors: by[source_name(a)].append(a)
    parts = ['%s (%d variants)' % (n, len(v)) if len(v) > 1 else n for n, v in sorted(by.items())]
    return ', '.join(parts[:limit]) + (', … %d more' % (len(parts) - limit) if len(parts) > limit else '')


def _maps(places, limit=8):
    maps = sorted({scene_name(p['scene']) for p in places})
    return ', '.join(maps[:limit]) + (', … %d more' % (len(maps) - limit) if len(maps) > limit else '')


def _merged(tabs):
    rows = {}
    for t, e in tabs:
        r = rows.setdefault(t, {'chance': [], 'count': e['count'], 'note': []})
        if e['chance'] not in r['chance']: r['chance'].append(e['chance'])
        if e['note'] and e['note'] not in r['note']: r['note'].append(e['note'])
    return sorted(rows.items())


def item_report(item, raw=False):
    out = []
    fixed = _cache['fixed'].get(item, [])
    if fixed:
        out.append('FIXED DROPS (always this item, no roll):')
        for p in sorted(fixed, key=lambda p: (scene_name(p['scene']), p['pos'])):
            out.append('  %s in %s   [%s]' % (source_name(p['actor']), where(p), p['actor']))
            out += ['      ' + c for c in conditions(p)]
        out.append('')
    tabs = _cache['by_item'].get(item, [])
    boost = low_boost(item)
    if tabs:
        d = data()
        out.append('RANDOM DROPS (drop tables that contain it):')
        out.append('  %      = chance this item is picked when the table rolls (one roll = one item)')
        if any(e['chance'].startswith('slot') for _, e in tabs):
            out.append('  slot N = "Max" table: one item per slot; a slot listing several items gives one of them')
        if any('boost' in e['chance'] for _, e in tabs):
            out.append('  boost only = 0% unless the low-resource boost below applies')
        out.append('')
        for t, r in _merged(tabs):
            extra = (', %d at once' % r['count']) if r['count'] != 1 else ''
            out.append('  %-38s %s%s%s' % (t, ' + '.join(r['chance']), extra,
                                           ('   (' + '; '.join(r['note']) + ')') if r['note'] else ''))
            users = sorted(a for a, tl in d['actors'].items() if tl and tl[0] == t)
            alt = sorted(a for a, tl in d['actors'].items() if t in tl[1:])
            placed = _cache['by_table'].get(t, [])
            if users: out.append('      default for: ' + _names(users))
            if alt: out.append('      optional for: ' + _names(alt))
            if placed: out.append('      placed %d times: %s' % (len(placed), _maps(placed)))
            if not (users or alt or placed): out.append('      no actor or placement uses it (may be picked by game code)')
        out.append('')
    g = global_rules(item)
    if g or (tabs and boost):
        out.append('RULES (global drop settings, apply to the random drops above):')
        out += ['  ' + x for x in g]
        if tabs: out += ['  low-resource boost: ' + x for x in boost]
        out.append('')
    if not fixed and not tabs: out.append('No drops found.')
    out.append('Double-click a table, actor or flag name to open it.')
    return '\n'.join(out)


def table_lines(t):
    out = []
    for e in entries(t):
        extra = (' x%d' % e['count']) if e['count'] != 1 else ''
        out.append('  %-38s %s%s%s' % (e['item'], e['chance'], extra, ('   ' + e['note']) if e['note'] else ''))
    return out or ['  (nothing)']


def table_report(t, raw=False):
    d = data()
    tb = d['tables'].get(t, {})
    out = ['%s%s' % (t, ('   (name: %s)' % tb['name']) if tb.get('name') and tb['name'] != t else ''), '', 'DROPS (one roll picks one row):']
    out += table_lines(t)
    out.append('')
    users = sorted(a for a, tl in d['actors'].items() if t in tl)
    if users:
        out.append('ACTORS THAT CAN USE IT:')
        out += ['  %s [%s]%s' % (source_name(a), a, '  (default)' if d['actors'][a][0] == t else '') for a in users]
        out.append('')
    placed = _cache['by_table'].get(t, [])
    if placed:
        out.append('PLACED (%d):' % len(placed))
        for scene, ps in _group(placed):
            out.append('  %s: %s' % (scene_name(scene), ', '.join(sorted({'%s x%d' % (source_name(a), sum(1 for p in ps if p['actor'] == a)) for a in {p['actor'] for p in ps}}))))
        out.append('')
    out += [LOCK, '']
    if raw:
        out.append('RAW:')
        out.append('  ' + json.dumps(tb, ensure_ascii=False))
        for s in tb.get('subs', []): out.append('  %s = %s' % (s, json.dumps(d['subs'].get(s), ensure_ascii=False)))
    return '\n'.join(out)


def source_report(a, raw=False):
    d = data()
    tl = d['actors'].get(a, [])
    out = ['%s  [%s]' % (source_name(a), a), '']
    if tl:
        out.append('DEFAULT DROP TABLE: %s' % tl[0])
        out += table_lines(tl[0])
        out.append('')
        if len(tl) > 1:
            out.append('OTHER TABLES IT CAN USE (picked per placement with Drop__DropTable, or by the actor itself):')
            for t in tl[1:]:
                out.append('  %s: %s' % (t, ', '.join('%s %s' % (e['item'], e['chance']) for e in entries(t)) or 'nothing'))
            out.append('')
    places = [p for p in d['placed'] if p['actor'] == a]
    if places:
        out.append('PLACED (%d):' % len(places))
        for p in sorted(places, key=lambda p: (scene_name(p['scene']), p['pos'])):
            fixed = p['params'].get('Drop__DropActor')
            what = ('drops %s' % item_name(fixed)) if fixed else ('table %s' % table_of(p)) if table_of(p) else 'no drop (set on this placement)'
            out.append('  %s   %s' % (where(p), what))
            if fixed or raw: out += ['      ' + c for c in conditions(p)]
        out.append('')
    if tl: out.append(LOCK)
    if not tl and not places: out.append('No drop data.')
    return '\n'.join(out)


def map_report(scene, raw=False):
    ps = [p for p in data()['placed'] if map_key(p['scene']) == scene]
    out = ['%s  [%s]' % (scene_name(scene), scene), '']
    fixed = [p for p in ps if p['params'].get('Drop__DropActor')]
    if fixed:
        out.append('FIXED DROPS / CHEST CONTENTS:')
        for p in sorted(fixed, key=lambda p: p['pos']):
            out.append('  %-26s %s   from %s at %s' % (item_name(p['params']['Drop__DropActor']), '', source_name(p['actor']),
                                                  tuple(p['pos'])))
            out += ['      ' + c for c in conditions(p) if raw or not c.endswith('(map version)')]
        out.append('')
    rnd = defaultdict(list)
    for p in ps:
        if p['params'].get('Drop__DropActor'): continue
        t = table_of(p)
        if t and t != 'DropTable_None': rnd[(p['actor'], t)].append(p)
    if rnd:
        out.append('RANDOM DROPS:')
        for (a, t), ql in sorted(rnd.items(), key=lambda kv: source_name(kv[0][0])):
            out.append('  %s [%s] x%d   table %s: %s' % (source_name(a), a, len(ql), t,
                       ', '.join('%s %s' % (e['item'], e['chance']) for e in entries(t)) or
                       ('nothing' if t in data()['tables'] else 'not in the drop files')))
            if raw: out += ['      at %s' % (tuple(p['pos']),) for p in ql]
        out.append('')
    return '\n'.join(out)
