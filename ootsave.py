#!/usr/bin/env python3
"""Command-line tool for Ocarina of Time (Switch 2) saves. See ootcore.py for the format."""
import argparse, json, re, sys

from ootcore import NAMES, Save, diff, label, murmur3, resolve


def cmd_list(a):
    s = Save(a.save)
    rx = re.compile(a.filter, re.I) if a.filter else None
    for h, (t, _) in s.entries.items():
        if a.type and t != a.type: continue
        lab = label(h)
        if rx and not rx.search(lab) and not rx.search('%08x' % h): continue
        if a.unnamed and h in NAMES: continue
        val = s.get(h)
        if a.set_only and val in (False, 0, 0.0, '', [], None): continue
        print('%08x  %-12s %s = %s' % (h, t, lab, json.dumps(val, ensure_ascii=False)))


def cmd_get(a):
    s = Save(a.save)
    for k in a.flags:
        h = resolve(k)
        if h not in s.entries: print('%s: not in save' % k); continue
        print('%08x  %s = %s' % (h, label(h), json.dumps(s.get(h), ensure_ascii=False)))


def cmd_set(a):
    s = Save(a.save)
    for pair in a.assign:
        k, _, v = pair.partition('=')
        h = resolve(k)
        if h not in s.entries: sys.exit('%s: not in save' % k)
        old = s.get(h)
        try: s.set(h, v)
        except ValueError as e: sys.exit('%s: %s' % (k, e))
        print('%s: %s -> %s' % (label(h), json.dumps(old), json.dumps(s.get(h))))
    s.write()
    print('written (original kept as %s.bak)' % a.save)


def cmd_diff(a):
    for h, t, va, vb in diff(Save(a.a), Save(a.b)):
        print('%08x  %-12s %s: %s -> %s' % (h, t, label(h), json.dumps(va, ensure_ascii=False)[:200],
                                          json.dumps(vb, ensure_ascii=False)[:200]))


def cmd_hash(a):
    for s in a.strings:
        h = murmur3(s)
        print('%08x  %s%s' % (h, s, '   (known: %s)' % NAMES[h] if h in NAMES else ''))


def cmd_why(a):
    import ootrefs
    if not ootrefs.available(): sys.exit('reference data missing: run the build_*.py scripts first')
    for q in a.names:
        print('== %s\n%s\n' % (q, ootrefs.report(q)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest='cmd', required=True)
    q = sp.add_parser('list', help='list flags'); q.add_argument('save')
    q.add_argument('-f', '--filter', help='regex on name/actor/hash'); q.add_argument('-t', '--type')
    q.add_argument('-s', '--set-only', action='store_true', help='hide false/0/empty values')
    q.add_argument('-u', '--unnamed', action='store_true', help='only flags without a recovered name')
    q.set_defaults(fn=cmd_list)
    q = sp.add_parser('get', help='print flags by name or hash'); q.add_argument('save'); q.add_argument('flags', nargs='+')
    q.set_defaults(fn=cmd_get)
    q = sp.add_parser('set', help='set flags: name=value'); q.add_argument('save'); q.add_argument('assign', nargs='+')
    q.set_defaults(fn=cmd_set)
    q = sp.add_parser('diff', help='show flags that differ between two saves'); q.add_argument('a'); q.add_argument('b')
    q.set_defaults(fn=cmd_diff)
    q = sp.add_parser('hash', help='murmur3 a name and check it'); q.add_argument('strings', nargs='+')
    q.set_defaults(fn=cmd_hash)
    q = sp.add_parser('why', help='what sets/checks/triggers a flag, Step_* story step, event id or cutscene')
    q.add_argument('names', nargs='+'); q.set_defaults(fn=cmd_why)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
