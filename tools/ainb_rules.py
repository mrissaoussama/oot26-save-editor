"""Structured condition trees from AINB logic modules, for the plain-English report.

A condition is ('AND'|'OR', [children]), ('NOT', child) or a leaf dict
{'t': text, 'edit': [flag, value] or None, 'do': player action or None}.
"""
from ainb_render import Renderer, _outputs


def strip_id(inst):
    """Area_8ff7 -> Area, Obj_TimeTemple_MasterSword_A_01_e482 -> Obj_TimeTemple_MasterSword_A_01"""
    parts = (inst or '?').rsplit('_', 1)
    if len(parts) == 2 and len(parts[1]) == 4 and all(c in '0123456789abcdef' for c in parts[1]):
        return parts[0]
    return inst or '?'


def challenge(path):
    return 'Step_' + (path or '?').rsplit('/', 1)[-1].split('.')[0]


def leaf(t, edit=None, do=None):
    return {'t': t, 'edit': edit, 'do': do}


class Rules(Renderer):
    EFFECT = {'Logic_Create': '%s is present', 'Logic_Delete': '%s is removed', 'isOpen': '%s is open',
              'isClose': '%s is closed', 'EnableLockOn': '%s can be targeted'}

    def __init__(self, d, refs=None):
        super().__init__(d)
        self.refs = refs or {}

    def val(self, n, pname):
        for lst in (n.get('Properties') or {}).values():
            for p in lst:
                if p['Name'] == pname: return p.get('Default Value')
        for lst in ((n.get('Parameters') or {}).get('Inputs') or {}).values():
            for p in lst:
                if p['Name'] == pname: return p.get('Default Value')
        return None

    def srcs(self, n, pname):
        for typ, lst in ((n.get('Parameters') or {}).get('Inputs') or {}).items():
            for p in lst:
                if p['Name'] != pname: continue
                return [(s['Node Index'], s.get('Output Index', 0), typ)
                        for s in p.get('Sources', [p]) if s.get('Node Index', -1) >= 0]
        return []

    def actor(self, inst):
        r = self.refs.get(inst) or {}
        return r.get('gyaml') or strip_id(inst), r

    def cond(self, ni, oi, typ, depth=0):
        n = self.nodes.get(ni)
        if n is None or depth > 14: return leaf('?')
        nm = n['Name']
        outs = _outputs(n, typ)
        o = outs[oi] if 0 <= oi < len(outs) else ''

        def kids(p):
            return [self.cond(a, b, c, depth + 1) for a, b, c in self.srcs(n, p)]

        if nm.startswith('Operate') and ('AND' in nm or 'OR' in nm):
            ks = kids('BoolMulti')
            c = ks[0] if len(ks) == 1 else ('AND' if nm[7:].startswith('AND') else 'OR', ks)
            return ('NOT', c) if o == 'False' else c
        if nm.startswith('OperateCompare'):
            def side(x):
                src = self.srcs(n, x)
                if not src: return str(self.val(n, x))
                sn = self.nodes.get(src[0][0], {})
                so = _outputs(sn, src[0][2])
                oname = so[src[0][1]] if src[0][1] < len(so) else '?'
                inst = self.val(sn, 'InstanceName')
                return '%s %s' % (self.actor(inst)[0], oname) if inst else '%s.%s' % (sn.get('Name', '?'), oname)
            op = {'Equal': '=', 'A_Bigger': '>', 'B_Bigger': '<', 'NotEqual': '!='}.get(o, o)
            return leaf('%s %s %s' % (side('Int_A'), op, side('Int_B')))
        if 'InvBool' in nm or 'InvertBool' in nm or nm == 'OperateNOT':
            ks = kids('BoolMulti') or kids('Bool') or [leaf('?')]
            return ('NOT', ks[0])
        if nm == 'HoldChallengeCurrentStepCheckOrder':
            st, s = challenge(self.val(n, 'ChallengeName')), self.val(n, 'ChallengeStepName')
            if o == 'IsEqual': return leaf('%s is exactly %s' % (st, s), [st, s])
            if o == 'IsAfter': return leaf('%s is past %s' % (st, s), [st, 'any step after ' + s])
            if o == 'IsBefore': return leaf('%s is before %s' % (st, s), [st, 'any step before ' + s])
            return leaf('%s %s %s' % (st, o, s))
        if nm.startswith('HoldActorObserverBySensorHitInfo'):
            who = self.val(n, 'ActorName') or '?'
            who = 'player' if who == 'Player' else who
            zones = []
            for a, _, _ in self.srcs(n, 'SensorHitInfoMulti') or self.srcs(n, 'SensorHitInfo'):
                inst = self.val(self.nodes.get(a, {}), 'InstanceName') or '?'
                _, r = self.actor(inst)
                zones.append('zone %s%s' % (inst, ' at %s' % r['pos'] if r.get('pos') else ''))
            zs = ' or '.join(zones) or 'a zone'
            if o == 'IsNotHit': return leaf('%s is NOT inside %s' % (who, zs))
            return leaf('%s is inside %s' % (who, zs), do=('walk into %s' % zs) if who == 'player' else None)
        if nm.startswith('HoldGameDataGetBoolExp'):
            f = self.val(n, 'GameDataNameBoolExp')
            return leaf(f, ['EXP', f])
        if nm.startswith('HoldGameDataGetBool'):
            f = self.val(n, 'GameDataNameBool')
            return leaf('%s is true' % f, [f, 'true'])
        if nm == 'HoldGameDataHavePlayedEvent':
            e = self.val(n, 'EventName')
            if o == 'NoPlay': return leaf('event %s has NOT been played yet' % e, ['HavePlayedEvent.' + e, 'false'])
            return leaf('event %s has been played' % e, ['HavePlayedEvent.' + e, 'true'])
        if nm.startswith('HoldGameDataGetInt'):
            f = self.val(n, 'GameDataNameInt') or self.val(n, 'GameDataName')
            return leaf('%s (%s)' % (f, o))
        if o == 'ReceiveDoAction':
            a, _ = self.actor(self.val(n, 'InstanceName'))
            return leaf('player presses A on %s' % a, do='press A on %s' % a)
        if nm == 'ActorLogicEventRequestActor':
            _, r = self.actor(self.val(n, 'InstanceName'))
            ev = (r.get('dyn') or {}).get('RequestEventName', '?')
            return leaf('event %s finished' % ev if o == 'EventFinish' else 'event %s signals %s' % (ev, o))
        if nm.startswith('HoldBlackboard'):
            return leaf('internal state %s' % self.val(n, 'BlackboardKey'))
        if nm.startswith('ActorLogic'):
            a, _ = self.actor(self.val(n, 'InstanceName'))
            return leaf('%s: %s' % (a, o))
        return leaf(self.out(ni, oi, 8, typ))

    def rules(self):
        out = []
        for n in self.nodes.values():
            nm = n['Name']
            if nm.startswith('Hold') or nm.startswith('Operate') or 'InvBool' in nm: continue
            for typ, lst in ((n.get('Parameters') or {}).get('Inputs') or {}).items():
                if typ != 'Bool': continue
                for p in lst:
                    s = self.srcs(n, p['Name'])
                    if not s: continue
                    pn = p['Name']
                    if pn == 'EventRequestTrigger':
                        _, r = self.actor(self.val(n, 'InstanceName'))
                        ev = (r.get('dyn') or {}).get('RequestEventName', '?')
                        eff, kind = 'starts event %s' % ev, 'event'
                    elif pn == 'IsDrive' and nm.startswith('TriggerGameDataSetBool'):
                        eff = 'sets %s = %s' % (self.val(n, 'GameDataNameBool'), 'true' if nm.endswith('True') else 'false')
                        kind = 'set'
                    elif pn in self.EFFECT:
                        a, _ = self.actor(self.val(n, 'InstanceName'))
                        eff, kind = self.EFFECT[pn] % a, 'actor'
                    elif pn in ('IsSkipAnim', 'SensorHitInfoMulti'):
                        continue
                    else:
                        a, _ = self.actor(self.val(n, 'InstanceName') or nm)
                        eff, kind = '%s: %s' % (a, pn), 'other'
                    cs = [self.cond(a, b, t) for a, b, t in s]
                    out.append({'effect': eff, 'kind': kind, 'cond': cs[0] if len(cs) == 1 else ('OR', cs)})
        return out
