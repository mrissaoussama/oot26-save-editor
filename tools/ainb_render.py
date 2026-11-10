"""Readable formulas for AINB logic modules (romfs/Logic/*.ainb). Needs `pip install ainb`."""
from ainb.ainb import AINB

SKIP_IN = {'Logic_Create', 'Logic_Delete', 'RespawnTrigger'}


def load(data):
    return AINB.from_binary(data).as_dict()


def _props(n):
    out = []
    for typ, lst in (n.get('Properties') or {}).items():
        for p in lst:
            v = p.get('Default Value')
            if v in ('', None) or p['Name'] in ('AddLayer',): continue
            out.append('%s=%s' % (p['Name'], v))
    return out


def _outputs(n, typ=None):
    outs = (n.get('Parameters') or {}).get('Outputs') or {}
    if typ in outs: return [o['Name'] for o in outs[typ]]
    return [o['Name'] for lst in outs.values() for o in lst]


class Renderer:
    def __init__(self, d):
        self.nodes = {n['Node Index']: n for n in d.get('Nodes', [])}
        self.name = d.get('Filename', '')

    def src(self, inp, depth, typ=None):
        if 'Sources' in inp:
            return [self.src(s, depth, typ) for s in inp['Sources']]
        ni = inp.get('Node Index', -1)
        if ni is None or ni < 0:
            return None
        return self.out(ni, inp.get('Output Index', 0), depth, typ)

    def out(self, ni, oi, depth=0, typ=None):
        n = self.nodes.get(ni)
        if n is None: return '?node%d' % ni
        outs = _outputs(n, typ)
        oname = outs[oi] if 0 <= oi < len(outs) else str(oi)
        args = self.args(n, depth + 1) if depth < 12 else ['...']
        nm = n['Name']
        if nm.startswith('Operate') and nm[7:] in ('AND', 'OR', 'NOT', 'XOR'):
            r = '%s(%s)' % (nm[7:], ', '.join(a.split('=', 1)[-1] for a in args if not a.startswith('UpdateOnce')))
            return 'NOT ' + r if oname == 'False' else r
        suffix = '' if oname in ('Result', 'Value', 'Out', 'Output', 'True') or len(outs) <= 1 else '.' + oname
        return '%s(%s)%s' % (nm, ', '.join(args), suffix)

    def args(self, n, depth):
        res = _props(n)
        for typ, lst in ((n.get('Parameters') or {}).get('Inputs') or {}).items():
            for p in lst:
                s = self.src(p, depth, typ)
                if p['Name'] in SKIP_IN and not s: continue
                if isinstance(s, list):
                    res.append('%s=%s' % (p['Name'], ', '.join(x for x in s if x)))
                elif s:
                    res.append('%s=%s' % (p['Name'], s))
                elif 'Uses Default' not in p.get('Flags', []) or p.get('Default Value') not in (False, 0, '', None):
                    v = p.get('Default Value')
                    if v not in ('', None): res.append('%s=%s' % (p['Name'], v))
        return res

    def roots(self):
        """Nodes whose outputs nobody consumes: the things the module drives (event requests, flag writes, actors)."""
        used = set()

        def mark(inp):
            for s in inp.get('Sources', [inp]):
                if s.get('Node Index', -1) >= 0: used.add(s['Node Index'])
        for n in self.nodes.values():
            for typ, lst in ((n.get('Parameters') or {}).get('Inputs') or {}).items():
                for p in lst: mark(p)
        return [i for i in self.nodes if i not in used]

    def render(self):
        lines = []
        for i in self.roots():
            n = self.nodes[i]
            args = self.args(n, 1)
            if not args: continue
            lines.append('%s:' % n['Name'])
            for a in args: lines.append('    ' + a)
        return '\n'.join(lines)
