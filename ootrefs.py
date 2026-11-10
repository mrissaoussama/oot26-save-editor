"""Cross-reference: what sets, checks or is triggered by a flag, story step, event or cutscene.

Data is built by tools/build_all.py: events/, event_index.json, logic/, scene_index.json.
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
_cache = {}


def _load(name, default):
    p = os.path.join(HERE, name)
    if not os.path.exists(p): return default
    with open(p, encoding='utf8') as f: return json.load(f)


def data():
    if _cache: return _cache
    _cache['exp'] = _load('boolexp.json', {})
    _cache['ev'] = _load('event_index.json', {'flags': {}, 'challenge_steps': {}, 'cutscenes': {}, 'subflow_callers': {}})
    _cache['scene'] = _load('scene_index.json', [])
    _cache['rsdb'] = {e['__RowId']: e for e in _load('rsdb_eventsetting.json', [])}
    logic = {}
    d = os.path.join(HERE, 'logic')
    if os.path.isdir(d):
        for fn in os.listdir(d):
            with open(os.path.join(d, fn), encoding='utf8') as f: logic[fn[:-4]] = f.read()
    _cache['logic'] = logic
    flows = {}
    d = os.path.join(HERE, 'events')
    if os.path.isdir(d):
        for fn in os.listdir(d):
            with open(os.path.join(d, fn), encoding='utf8') as f: flows[fn[:-4]] = f.read()
    _cache['flows'] = flows
    plain = {}
    d = os.path.join(HERE, 'events_plain')
    if os.path.isdir(d):
        for fn in os.listdir(d):
            with open(os.path.join(d, fn), encoding='utf8') as f: plain[fn[:-4]] = f.read()
    _cache['plain'] = plain
    _cache['rules'] = _load('logic_rules.json', [])
    return _cache


def available():
    return os.path.exists(os.path.join(HERE, 'event_index.json'))


def _word(s):
    return re.compile(r'(?<![A-Za-z0-9_.])%s(?![A-Za-z0-9_])' % re.escape(s))


def _short(s, n=600):
    return s if len(s) <= n else s[:n] + ' …'


def flow_entry(flow, entry):
    txt = data()['flows'].get(flow, '')
    m = re.search(r'^== entry %s\n(.*?)(?=^== entry |\Z)' % re.escape(entry), txt, re.M | re.S)
    return m.group(1).rstrip() if m else ''


def _logic_hits(rx, limit=40):
    out = []
    for name, txt in sorted(data()['logic'].items()):
        if not rx.search(txt): continue
        scenes = sorted(set(re.findall(r'^# used in scene (\S+)', txt, re.M)))
        lines = [l.strip() for l in txt.split('\n') if rx.search(l) and not l.startswith('#')]
        out.append('  %s  (scene: %s)' % (name, ', '.join(scenes) or '?'))
        # the line that drives something is the most useful context: show its owner too
        body = txt.split('\n')
        for i, l in enumerate(body):
            if l.startswith('#') or not rx.search(l): continue
            owner = next((body[j] for j in range(i, -1, -1) if body[j] and not body[j].startswith(' ')), '')
            out.append('      %s  %s' % (owner, _short(l.strip(), 900)))
            if len(out) > limit * 4: break
        if len(out) > limit * 4:
            out.append('  …'); break
    return out


def report(q, raw=False):
    """Readable report by default; raw=True gives the technical one."""
    if raw: return raw_report(q)
    import ootplain
    return ootplain.report(q)


def raw_report(q):
    """Plain-text report for a flag name, Step_* enum, event id, flow entry or cutscene name."""
    q = q.strip()
    D = data()
    rx = _word(q)
    out = []

    if q in D['exp']:
        out += ['COMPUTED FLAG (not stored, evaluated from other flags):', '  %s = %s' % (q, D['exp'][q]), '']

    users = [k for k, v in D['exp'].items() if rx.search(v)]
    if users:
        out.append('Computed flags that depend on it:')
        out += ['  %s = %s' % (k, D['exp'][k]) for k in sorted(users)[:60]]
        out.append('')

    if q.startswith('Step_'):
        chal = q[5:]
        steps = {k: v for k, v in D['ev']['challenge_steps'].items() if k.split('.')[0] == chal}
        if steps:
            out.append('Story step "%s": which event advances it to each step' % chal)
            for k in sorted(steps): out.append('  -> %-12s by %s' % (k.split('.', 1)[1] or '(start)', ', '.join(steps[k])))
            out.append('')
        crx = re.compile(r'Challenge/%s\.game__challenge' % re.escape(chal))
        hits = _logic_hits(crx)
        if hits:
            out.append('Scene logic that checks this story step (HoldChallengeCurrentStepCheckOrder):')
            out += hits; out.append('')

    f = D['ev']['flags'].get(q) or D['ev']['flags'].get('HavePlayedEvent.' + q)
    if f:
        for role in ('sets', 'checks', 'uses'):
            if f.get(role):
                out.append('Event flows that %s it:' % role.replace('uses', 'use'))
                out += ['  ' + _short(x, 400) for x in f[role][:60]]
                out.append('')

    if q in D['ev']['cutscenes']:
        out.append('Cutscene/event played by:')
        out += ['  ' + x for x in D['ev']['cutscenes'][q]]
        out.append('')

    ent = D['rsdb'].get(q)
    entries = []
    if ent and ent.get('EntryPointName'):
        entries.append((os.path.basename(ent['FlowchartFileName']).split('.')[0], ent['EntryPointName'], q))
    for rid, e in D['rsdb'].items():
        if e.get('EntryPointName') == q and rid != q:
            entries.append((os.path.basename(e['FlowchartFileName']).split('.')[0], q, rid))
    for flow, entry, rid in entries:
        out.append('EVENT %s  ->  flow %s, entry %s' % (rid, flow, entry))
        reqs = [a for a in D['scene'] if rid in json.dumps(a['params'], ensure_ascii=False)]
        for a in reqs:
            out.append('  requested by %s in scene %s at %s  logic: %s' % (a['actor'], a['scene'], a['pos'], ', '.join(a['logic']) or '-'))
            for lg in a['logic']:
                txt = D['logic'].get(lg, '')
                for block in re.split(r'\n(?=\S)', txt):
                    if rid in block and not block.startswith('#'):
                        out.append('    ' + _short(block.replace('\n', '\n    '), 3000))
        callers = D['ev']['subflow_callers'].get('%s<%s>' % (flow, entry))
        if callers: out.append('  called from: ' + ', '.join(callers))
        body = flow_entry(flow, entry)
        if body:
            out.append('  flow:')
            out += ['    ' + l for l in body.split('\n')[:80]]
        out.append('')

    sc = [a for a in D['scene'] if rx.search(json.dumps(a['params'], ensure_ascii=False))]
    if sc:
        out.append('Scene actors with it in their parameters:')
        for a in sc[:40]:
            out.append('  %s %s in %s at %s  %s' % (a['actor'], a['name'], a['scene'], a['pos'],
                                                  _short(json.dumps(a['params'], ensure_ascii=False), 300)))
        out.append('')

    if not q.startswith('Step_'):
        hits = _logic_hits(rx)
        if hits:
            out.append('Scene logic (area triggers, actor spawn/delete, event requests) that uses it:')
            out += hits; out.append('')

    if not out:
        return 'No references found for %s.\n(Many flags are only read by game code, which is not decoded.)' % q
    return '\n'.join(out)


KINDS = ('All', 'Events', 'Story steps', 'Flags', 'Computed flags', 'Cutscenes')


def catalog():
    """name -> kind for everything the explorer can show."""
    D = data()
    if 'catalog' in D: return D['catalog']
    import ootcore
    cat = {}
    for n in ootcore.BY_NAME: cat[n] = 'Flags'
    for n in D['ev']['flags']: cat.setdefault(n, 'Flags')
    for n in D['exp']: cat[n] = 'Computed flags'
    for n in D['ev']['cutscenes']: cat.setdefault(n, 'Cutscenes')
    for rid, e in D['rsdb'].items():
        if e.get('EntryPointName'): cat[rid] = 'Events'
    for flow, txt in D['plain'].items():
        for en in re.findall(r'^== entry (\S+)', txt, re.M): cat.setdefault(en, 'Events')
    for k in D['ev']['challenge_steps']: cat['Step_' + k.split('.')[0]] = 'Story steps'
    D['catalog'] = cat
    return cat


def search(q, kind='All', limit=5000):
    """Names matching every word of q (case-insensitive), optionally only one kind."""
    words = q.lower().split()
    return sorted(n for n, k in catalog().items()
                  if (kind == 'All' or k == kind) and all(w in n.lower() for w in words))[:limit]
