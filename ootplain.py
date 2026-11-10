"""Readable (non-technical) version of the cross-reference report. See ootrefs.py for the data."""
import re

import ootrefs

WORDS = [(re.compile(r'(\S+) >= (\S+)'), r'\1 is \2 or later'), (re.compile(r'(\S+) == (\S+)'), r'\1 is exactly \2'),
         (re.compile(r'(\S+) < (\S+)'), r'\1 is before \2'), (re.compile(r'(\S+) > (\S+)'), r'\1 is more than \2')]


def exp_words(name, depth=0):
    """Formula of a computed flag in words, nested computed flags expanded once."""
    f = ootrefs.data()['exp'].get(name)
    if f is None: return None
    if depth < 2:
        f = re.sub(r'\(([A-Za-z0-9_?.]+)\)', lambda m: '(%s)' % (exp_words(m.group(1), depth + 1) or m.group(1)), f)
    for rx, rep in WORDS: f = rx.sub(rep, f)
    return f


def annotate(text):
    """Append the meaning to computed-flag names inside a line."""
    def sub(m):
        w = exp_words(m.group(0))
        return '%s [= %s]' % (m.group(0), w) if w else m.group(0)
    return re.sub(r'[A-Za-z0-9_?]+_(?:Exp|BoolExp)\b|[A-Za-z0-9_]+_IsCompleted\b', sub, text)


def negate(t):
    for a, b in ((' is true', ' is false'), (' has been played', ' has NOT been played'),
                 (' has NOT been played yet', ' has been played'), (' is inside ', ' is NOT inside '),
                 (' is NOT inside ', ' is inside '), (' is exactly ', ' is NOT ')):
        if a in t: return t.replace(a, b, 1)
    return 'NOT: ' + t


def cond_lines(c, ind='  '):
    if isinstance(c, dict): return ['%s- %s' % (ind, annotate(c['t']))]
    op, x = c[0], c[1]
    if op == 'NOT':
        if isinstance(x, dict): return ['%s- %s' % (ind, annotate(negate(x['t'])))]
        return ['%s- NOT all of:' % ind] + cond_lines(x, ind + '    ')
    if op == 'AND':
        return [l for k in x for l in cond_lines(k, ind)]
    out = ['%s- one of these:' % ind]
    for k in x: out += cond_lines(k, ind + '    ')
    return out


def cond_short(c):
    if isinstance(c, dict): return c['t']
    op, x = c[0], c[1]
    if op == 'NOT': return negate(x['t']) if isinstance(x, dict) else 'NOT (%s)' % cond_short(x)
    return '(%s)' % (' %s ' % op).join(cond_short(k) for k in x) if len(x) > 1 else cond_short(x[0])


def how_to(c, edits, actions, neg=False):
    """Collect editor changes and in-game actions that make condition c true."""
    if isinstance(c, dict):
        if c.get('do') and not neg: actions.append(c['do'])
        e = c.get('edit')
        if not e: return
        flag, v = e
        if flag == 'EXP':
            w = exp_words(v)
            edits.append('make %s true%s' % (v, ': ' + w if w else '') if not neg else 'make %s false' % v)
        elif neg:
            edits.append('%s = %s' % (flag, {'true': 'false', 'false': 'true'}.get(v, 'anything except ' + v)))
        else:
            edits.append('%s = %s' % (flag, v))
        return
    op, x = c[0], c[1]
    if op == 'NOT': how_to(x, edits, actions, not neg)
    elif op == 'AND' and not neg:
        for k in x: how_to(k, edits, actions)
    elif x:
        how_to(x[0], edits, actions, neg)
        if len(x) > 1: edits.append('(that is one option; see "one of these" above)')


def event_ids(q):
    """[(event id, flow, entry)] for an event id or entry name."""
    D = ootrefs.data()
    out = []
    for rid, e in D['rsdb'].items():
        if not e.get('EntryPointName'): continue
        if rid == q or e['EntryPointName'] == q:
            out.append((rid, e['FlowchartFileName'].rsplit('/', 1)[-1].split('.')[0], e['EntryPointName']))
    if not out:
        rx = re.compile(r'^== entry %s$' % re.escape(q), re.M)
        out = [(q, flow, q) for flow, txt in D['plain'].items() if rx.search(txt)]
    return out


def plain_entry(flow, entry):
    txt = ootrefs.data()['plain'].get(flow, '')
    m = re.search(r'^== entry %s\n(.*?)(?=^== entry |\Z)' % re.escape(entry), txt, re.M | re.S)
    return [annotate(l) for l in m.group(1).rstrip().split('\n')] if m else []


def who_runs(flow, entry):
    """Other events/flows that play this entry."""
    D = ootrefs.data()
    return D['ev']['subflow_callers'].get('%s<%s>' % (flow, entry), [])


def pretty_where(w):
    flow, _, rest = w.partition('<')
    return '%s: %s' % (flow, rest.rstrip('>'))


def event_section(rid, flow, entry):
    D = ootrefs.data()
    out = ['EVENT %s' % rid, '  (flow %s, entry %s)' % (flow, entry), '']
    if rid not in D['rsdb']:
        out[-1:] = ['  Sub-event: has no event id of its own; it only runs when another event calls it.', '']
    rules = [r for r in D['rules'] if r['effect'] == 'starts event %s' % rid]
    if rules:
        for r in rules:
            out.append('STARTS WHEN all of these are true   (scene %s):' % ', '.join(r['scenes']))
            out += cond_lines(r['cond'])
            out.append('')
    else:
        actors = [a for a in D['scene'] if rid in a['params'].values()]
        for a in actors:
            if a['actor'] == 'EventProxyRequestActor':
                out.append('STARTS WHEN the player plays the ocarina (or uses the object) at the spot %s in scene %s.'
                           % (a['pos'], a['scene']))
                out.append('  The game then runs the checks below (e.g. right song, story step).')
            else:
                out.append('STARTED BY actor %s in scene %s at %s (condition handled by that actor).'
                           % (a['actor'], a['scene'], a['pos']))
        if actors: out.append('')
        callers = who_runs(flow, entry)
        rxs = re.compile(r'then starts %s\s*$' % re.escape(rid), re.M)
        for fl, txt in D['plain'].items():
            for m in rxs.finditer(txt):
                head = txt.rfind('== entry ', 0, m.start())
                en = txt[head + 9:txt.index('\n', head)] if head >= 0 else '?'
                callers.append('%s<%s>' % (fl, en + ', after an area change'))
        played = D['ev']['cutscenes'].get(rid, [])
        if actors: pass
        elif callers or played:
            out.append('STARTED BY other events:')
            out += ['  - ' + pretty_where(w) for w in sorted(set(callers + played))]
        else:
            out.append('STARTED BY: not found in scene logic (probably an NPC talk, item use or game code).')
        out.append('')
    steps = plain_entry(flow, entry)
    out.append('WHAT HAPPENS (camera, sound and animation steps hidden):')
    out += ['  ' + l for l in steps] if steps else ['  (only presentation; nothing saved)']
    out.append('')
    if rules:
        edits, actions = [], []
        how_to(rules[0]['cond'], edits, actions)
        if edits or actions:
            out.append('TO MAKE IT HAPPEN WITH THE EDITOR:')
            out += ['  %d. %s' % (i + 1, e if e.startswith('make') else 'set ' + e) if not e.startswith('(')
                    else '     %s' % e for i, e in enumerate(edits)]
            if actions and 'save, load' not in str(out[-1:]):
                out.append('  %d. save, load the slot, then in game: %s' % (len(edits) + 1, ' and '.join(dict.fromkeys(actions))))
            out.append('  Note: skipping earlier events skips what they give or set; check those events too.')
            out.append('')
    return out


def step_section(q):
    import ootcore
    D = ootrefs.data()
    chal = q[5:]
    out = ['STORY STEP %s' % q]
    h = ootcore.BY_NAME.get(q)
    order = ootcore.enum_choices(h) if h else []
    if order: out.append('  values in order: ' + ' > '.join(order))
    out.append('')
    steps = {k.split('.', 1)[1]: v for k, v in D['ev']['challenge_steps'].items() if k.split('.')[0] == chal}
    if steps:
        out.append('HOW EACH STEP IS REACHED:')
        for s in order + sorted(set(steps) - set(order) - {''}):
            if s in steps:
                out.append('  %-12s <- %s' % (s, '; '.join(pretty_where(w) for w in steps[s])))
        if '' in steps: out.append('  (quest started by: %s)' % '; '.join(pretty_where(w) for w in steps['']))
        out.append('')
    rx = re.compile(r'\b%s\b' % re.escape(q))
    deps = [r for r in D['rules'] if rx.search(str(r['cond']))]
    if deps:
        out.append('WHAT IN THE WORLD DEPENDS ON IT (%d rules):' % len(deps))
        for r in deps[:80]:
            out.append('  - %s   when %s   [%s]' % (r['effect'], annotate(cond_short(r['cond'])), ', '.join(r['scenes'])))
        out.append('')
    return out


def flag_section(q):
    D = ootrefs.data()
    out = []
    w = exp_words(q)
    if w:
        out += ['COMPUTED FLAG (not saved, worked out from other values):', '  %s' % w, '']
    f = D['ev']['flags'].get(q) or {}
    rx_val = re.compile(r'Value=(\S+?)[,\]]')
    if f.get('sets'):
        out.append('SET BY these events:')
        for x in f['sets'][:60]:
            where, _, detail = x.partition('  [')
            m = rx_val.search(detail)
            verb = 'adds %s' % m.group(1) if 'AddOrSub' in detail and m else '= %s' % m.group(1).lower() if m else ''
            out.append('  - %s   %s' % (pretty_where(where), verb))
        out.append('')
    if f.get('checks'):
        out.append('CHECKED BY these events:')
        out += ['  - ' + pretty_where(x.partition('  [')[0]) for x in f['checks'][:60]]
        out.append('')
    rx = re.compile(r'(?<![A-Za-z0-9_.])%s(?![A-Za-z0-9_])' % re.escape(q))
    rules = [r for r in D['rules'] if rx.search(r['effect']) or rx.search(str(r['cond']))]
    if rules:
        out.append('IN THE WORLD (scene logic):')
        for r in rules[:80]:
            out.append('  - %s   when %s   [%s]' % (r['effect'], annotate(cond_short(r['cond'])), ', '.join(r['scenes'])))
        out.append('')
    users = [k for k, v in D['exp'].items() if rx.search(v)]
    if users:
        out.append('USED IN COMPUTED FLAGS:')
        out += ['  - %s = %s' % (k, exp_words(k)) for k in sorted(users)[:40]]
        out.append('')
    if q in D['ev']['cutscenes']:
        out.append('PLAYED BY these events:')
        out += ['  - ' + pretty_where(x) for x in D['ev']['cutscenes'][q]]
        out.append('')
    return out


def report(q):
    q = q.strip()
    out = []
    if q.startswith('Step_'): out += step_section(q)
    for rid, flow, entry in event_ids(q): out += event_section(rid, flow, entry)
    if not q.startswith('Step_'): out += flag_section(q)
    if not out:
        return ('Nothing found for %s.\nSome flags are only read by game code, which could not be decoded.\n'
                'Tick "Technical details" for the raw search.' % q)
    return '\n'.join(out)
