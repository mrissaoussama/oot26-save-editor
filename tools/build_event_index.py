"""Dump every event flow to events/<name>.txt and build event_index.json (who sets / checks each flag)."""
from common import HERE, romfs_path, decompress
import json, os, sys

import evfl
from ootcore import BY_NAME

ROMFS = romfs_path()
OUT = os.path.join(HERE, 'events')
OUT_PLAIN = os.path.join(HERE, 'events_plain')


def reach(chart):
    """event index -> set of entry names that can run it"""
    ev, res = chart['events'], {}
    for name, start in chart['entries'].items():
        stack, seen = [start], set()
        while stack:
            i = stack.pop()
            if i == evfl.NONE or i in seen: continue
            seen.add(i); res.setdefault(i, set()).add(name)
            e = ev[i]
            if 'next' in e: stack.append(e['next'])
            if 'cases' in e: stack += [t for _, t in e['cases']]
            if 'forks' in e: stack += e['forks'] + [e['join']]
    return res


def role(call):
    if 'Query' in call: return 'checks'
    if any(k in call for k in ('Set', 'AddOrSub', 'Reset', 'Increment', 'Progress')): return 'sets'
    return 'uses'


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(OUT_PLAIN, exist_ok=True)
    flags = {}
    steps = {}
    cutscenes = {}
    calls = {}
    src = os.path.join(ROMFS, 'Event', 'EventFlow')
    n = 0
    for fn in sorted(os.listdir(src)):
        if not fn.endswith('.bfevfl.zs'): continue
        try: f = evfl.Flow(decompress(open(os.path.join(src, fn), 'rb').read()))
        except Exception as e:
            print('skip', fn, e); continue
        base = fn[:-len('.bfevfl.zs')]
        with open(os.path.join(OUT_PLAIN, base + '.txt'), 'w', encoding='utf8') as w:
            for c in f.charts:
                for en, st in c['entries'].items():
                    w.write('== entry %s\n' % en)
                    w.write(''.join('  %s\n' % l for l in evfl.plain(c, st)) + '\n')
        with open(os.path.join(OUT, base + '.txt'), 'w', encoding='utf8') as w:
            for c in f.charts:
                w.write('# flow %s\n' % c['name'])
                w.write(evfl.render(c) + '\n')
                r = reach(c)
                for i, e in enumerate(c['events']):
                    where = ['%s<%s>' % (base, en) for en in sorted(r.get(i, ['?']))]
                    if e['type'] in (evfl.SUBFLOW, evfl.CALLSWITCH):
                        for wh in where: calls.setdefault('%s<%s>' % (e['flow'] or base, e['entry']), set()).add(wh)
                    if 'params' not in e or e['type'] in (evfl.SUBFLOW, evfl.CALLSWITCH): continue
                    p, call = e['params'], e.get('call', '')
                    if 'ChallengeName' in p:
                        k = '%s.%s' % (p['ChallengeName'], p.get('StepName', ''))
                        for wh in where: steps.setdefault(k, set()).add(wh)
                    if call == 'EventTransition' and p.get('EventName'):
                        for wh in where: cutscenes.setdefault(p['EventName'], set()).add(wh)
                    for k, v in p.items():
                        if not isinstance(v, str): continue
                        if k in ('EventName',) and 'HavePlayed' in call: v = 'HavePlayedEvent.' + v
                        if v not in BY_NAME: continue
                        what = role(call)
                        detail = '%s %s' % (call, ', '.join('%s=%s' % (a, b) for a, b in p.items()
                                                            if a not in ('Index', 'GameDataName', 'IsWaitEnd')))
                        for wh in where:
                            flags.setdefault(v, {}).setdefault(what, set()).add('%s  [%s]' % (wh, detail.strip()))
        n += 1
    js = lambda d: {k: sorted(v) if isinstance(v, set) else {a: sorted(b) for a, b in v.items()} for k, v in sorted(d.items())}
    json.dump({'flags': js(flags), 'challenge_steps': js(steps), 'cutscenes': js(cutscenes), 'subflow_callers': js(calls)},
              open(os.path.join(HERE, 'event_index.json'), 'w', encoding='utf8'), indent=1, ensure_ascii=False)
    print('%d flows, %d flags, %d challenge steps, %d cutscenes' % (n, len(flags), len(steps), len(cutscenes)))


if __name__ == '__main__':
    main()
