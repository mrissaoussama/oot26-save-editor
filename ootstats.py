"""Readable enemy / Link / weapon stats from actor_stats.json."""
import json, math, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
KINDS = ('All', 'Link', 'Enemies', 'Bosses', 'Weapons & items', 'Projectiles', 'Other')
PER_HEART = 4
_cache = {}


def data():
    if not _cache:
        p = os.path.join(HERE, 'actor_stats.json')
        _cache['a'] = json.load(open(p, encoding='utf8')) if os.path.exists(p) else {}
    return _cache['a']


def available():
    return bool(data())


def kind(name, v):
    if v['category'] == 'Other' and re.search(r'Bullet|Arrow|Beam|FireBall|Breath|Shock|Thunder|Squirt', name):
        return 'Projectiles'
    return v['category']


def search(q, k='All', limit=5000):
    words = q.lower().split()
    return sorted(n for n, v in data().items()
                  if (k == 'All' or kind(n, v) == k) and all(w in n.lower() for w in words))[:limit]


def pick(files, prefix, actor=None):
    """The file under prefix, preferring the one named after the actor."""
    hits = [k for k in files if k.startswith(prefix)]
    if not hits: return {}
    own = [k for k in hits if actor and '/%s.' % actor.replace('Enemy_', '') in k.replace('Enemy_', '')]
    return files[(own or hits)[0]]


def num(x):
    if isinstance(x, float):
        return ('%.3f' % x).rstrip('0').rstrip('.')
    return str(x)


def hearts(v):
    h = v / PER_HEART
    return '%s heart%s' % (num(h), '' if h == 1 else 's')


def attacks(files, actor):
    ap = pick(files, 'GameBalance/AttackParam/', actor)
    if not ap: return [], 0
    base = ap.get('BaseAttackPower', 0)
    rows = {}
    for k, v in ap.items():
        m = re.match(r'AttackParams\[(\d+)\]\.(\w+)$', k)
        if m: rows.setdefault(int(m.group(1)), {})[m.group(2)] = v
    return [rows[i] for i in sorted(rows)], base


def label(v):
    return '#%d' % v if isinstance(v, int) and not isinstance(v, bool) and v > 0xFFFF else str(v)


def attack_lines(rows, base, to_link=True):
    out = []
    for r in rows:
        mul = r.get('DamageMultiplier', 1.0)
        extra = [label(x) for x in (r.get('DamageAttributres') or []) + (r.get('DamageElements') or [])]
        dmg = base * mul
        val = ('%s = %s' % (num(dmg), hearts(dmg))) if to_link and base else 'x%s' % num(mul)
        out.append('  - %-26s %-14s %-12s %s%s' % (label(r.get('AttackType')), label(r.get('DamageType')),
                                                  label(r.get('DamageIntensity')), val,
                                                  '   [%s]' % ', '.join(extra) if extra else ''))
    return out


def weapon_table():
    out = []
    for n, v in sorted(data().items()):
        w = next((f for k, f in v['files'].items() if k.startswith('Component/WeaponParam/') and 'BaseAttack' in f), None)
        if w and w.get('BaseAttack') and n.startswith('Weapon_') and not n.endswith('_Base'):
            out.append((n, w['BaseAttack']))
    return out


_CATCH = None


def catchable():
    """{actor: reason} from catchable.json; empty if not built."""
    global _CATCH
    if _CATCH is None:
        try: _CATCH = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'catchable.json'), encoding='utf8'))
        except (OSError, ValueError): _CATCH = {}
    return _CATCH


def damage_rates(files):
    dp = next((f for k, f in files.items() if k.startswith('Life/DamageParameters/')), {})
    rates = {k.split('DamageRates.', 1)[1]: v for k, v in dp.items() if '.DamageRates.' in k}
    return rates, dp


def enemy(name, files):
    out = []
    life = pick(files, 'Life/LifeParameters/', name).get('MaxLife')
    if life is not None:
        out.append('HEALTH: %s' % life)
        ws = [(n, a) for n, a in weapon_table() if 'Poe' not in n and 'Dark' not in n]
        if ws:
            out.append('  hits needed (normal slash, damage x1): ' +
                       ', '.join('%s %d' % (n.replace('Weapon_Sword_', '').replace('Weapon_', ''), math.ceil(life / a))
                                 for n, a in ws))
        out.append('')
    rates, dp = damage_rates(files)
    if rates:
        out.append('DAMAGE IT TAKES (multiplier per damage type, 1 = normal):')
        imm = sorted(k for k, v in rates.items() if v == 0)
        odd = sorted((k, v) for k, v in rates.items() if v not in (0, 1))
        norm = sorted(k for k, v in rates.items() if v == 1)
        if imm: out.append('  immune (x0): ' + ', '.join(imm))
        for k, v in odd: out.append('  x%s: %s' % (num(v), k))
        if norm: out.append('  normal (x1): ' + ', '.join(norm))
        flags = [k.split('.')[-1] for k, v in dp.items() if v is True and k.split('.')[-1].startswith(('IsHeadshotOnly', 'IsForbidInstaKill', 'OnlyAffected'))]
        if flags: out.append('  special: ' + ', '.join(flags))
        out.append('')
    why = catchable().get(name)
    if why is None and any(isinstance(v, str) and 'CaptureActorCommon' in v
                           for k, f in files.items() if k.startswith('Component/LifeParam/') for v in f.values()):
        why = 'capture component'
    if why: out.append('CATCH IN A BOTTLE: yes (%s)' % why)
    elif name.startswith('Enemy_Poe'): out.append('CATCH IN A BOTTLE: no; its spirit (Obj_Spirit_Poe*) can be caught after it is defeated')
    else: out.append('CATCH IN A BOTTLE: no')
    out.append('')
    rows, base = attacks(files, name)
    if rows:
        out.append('ITS ATTACKS (damage to Link = base %s x multiplier; %d life = 1 heart):' % (num(base), PER_HEART))
        out.append('  %-28s %-14s %-12s %s' % ('attack', 'type', 'knock', 'damage'))
        out += attack_lines(rows, base)
        out.append('')
    return out


def link(name, files):
    out = []
    life = pick(files, 'Life/LifeParameters/').get('MaxLife')
    if life is not None:
        out.append('HEALTH: starts with %s life = %s (%d life = 1 heart here; the save stores PlayerStatus.Life / '
                   'MaxLife in 1/16 hearts, so 16 there = 1 heart)' % (life, hearts(life), PER_HEART))
        out.append('')
    gp = next((f for k, f in files.items() if k.startswith('Player/PlayerGameParam/')), {})
    groups = [('JUMP / CLIMB (metres)', r'^(Jump|StartJump|BackFlip|SideStep|BackStep|FrontStep|StepJump|Cliff|Clamber|StartClamber|PlayerStepHeight|PlayerHeight|PlayerCrouchHeight)'),
              ('MOVEMENT SPEED (m/s; no walk/run speed found in the params, probably animation-driven)',
               r'^(?!Guard|MoveShield|Climb|Spider|Medium|ShotInAir|Swim|Cucco).*(Speed(Mps)?|SpeedHeavy|SpeedScale)$'),
              ('SWIMMING', r'^Swim'),
              ('ITEMS / MAGIC', r'^(HoverBoots|NayruLove|MPUse|ChargeTime|Cucco|Hookshot|Bottle|FairyHeal|ContinuousHeal)'),
              ('DAMAGE / FALL', r'^(LargeLand|InvalidFall|Damage(?!Color)|InDown)')]
    used = set()
    for title, rx in groups:
        ks = [k for k in sorted(gp) if re.search(rx, k) and k not in used and not isinstance(gp[k], (list, str))]
        if not ks: continue
        used.update(ks)
        out.append(title + ':')
        out += ['  %-38s %s' % (k, num(gp[k])) for k in ks]
        out.append('')
    bh = next((f for k, f in files.items() if 'BottleHeal' in k), {})
    if bh:
        out.append('HEALING ITEMS (life restored, %d = 1 heart):' % PER_HEART)
        out += ['  %-20s %s' % (k, v) for k, v in sorted(bh.items())]
        out.append('')
    rates, _ = damage_rates(files)
    odd = sorted((k, v) for k, v in rates.items() if v != 1)
    if odd:
        out.append('DAMAGE LINK TAKES (non-normal multipliers):')
        out += ['  x%s: %s' % (num(v), k) for k, v in odd]
        out.append('')
    rows, _ = attacks(files, name)
    if rows:
        out.append("LINK'S ATTACKS (damage = weapon BaseAttack x multiplier):")
        out.append('  %-28s %-14s %-12s %s' % ('attack', 'type', 'knock', 'multiplier'))
        out += attack_lines(rows, 0, to_link=False)
        out.append('  (names shown as #number are not stored in the game data, only their hash)')
        out.append('')
    ws = weapon_table()
    if ws:
        out.append('WEAPON BASE DAMAGE:')
        out += ['  %-34s %s' % (n, a) for n, a in ws]
        out.append('')
    return out


def weapon(name, files):
    out = []
    w = next((f for k, f in sorted(files.items(), key=lambda kv: name not in kv[0])
              if k.startswith('Component/WeaponParam/') and 'BaseAttack' in f), None)
    if w:
        out.append('WEAPON:')
        for k in ('BaseAttack', 'GuardBreakPower', 'Range', 'WeaponType', 'SubType', 'Impulse', 'ImpulseLarge'):
            if k in w: out.append('  %-18s %s' % (k, ', '.join(map(label, w[k])) if isinstance(w[k], list) else label(num(w[k]) if isinstance(w[k], float) else w[k])))
        out.append('  (damage dealt = BaseAttack x the attack multiplier in Player_Child / Player_Adult)')
        out.append('')
    life = pick(files, 'Life/LifeParameters/', name).get('MaxLife')
    if life is not None: out += ['DURABILITY / LIFE: %s' % life, '']
    rows, base = attacks(files, name)
    if rows:
        out.append('ATTACKS (base %s):' % num(base))
        out += attack_lines(rows, base)
        out.append('')
    return out


def report(name, raw=False):
    a = data().get(name)
    if not a: return 'Nothing found for %s.' % name
    files = a['files']
    k = kind(name, a)
    out = ['%s   [%s]' % (name, k), '']
    if k == 'Link': out += link(name, files)
    elif k in ('Enemies', 'Bosses'): out += enemy(name, files)
    elif k == 'Weapons & items': out += weapon(name, files)
    else: out += enemy(name, files)
    if raw or len(out) <= 2:
        out.append('ALL PARAMETERS (merged with their parent files):')
        for f, kv in sorted(files.items()):
            out.append('  [%s]' % f)
            out += ['      %s = %s' % (p, v) for p, v in kv.items()]
    else:
        out.append('Tick "All parameters" to see every value and the file it comes from.')
    return '\n'.join(out)
