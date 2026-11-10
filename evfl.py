"""Parser for BFEVFL v4 event flows (romfs/Event/EventFlow/*.bfevfl.zs)."""
import struct

ACTION, SWITCH, FORK, JOIN, SUBFLOW, CALLSWITCH, RETURN = range(7)


class Flow:
    def __init__(self, data):
        self.d = d = data
        if d[:6] != b'BFEVFL': raise ValueError('not a bfevfl')
        nflow = struct.unpack_from('<H', d, 0x20)[0]
        self.charts = [self.chart(self.q(self.q(0x28) + 8 * i)) for i in range(nflow)]

    def q(self, o): return struct.unpack_from('<Q', self.d, o)[0]
    def h(self, o): return struct.unpack_from('<H', self.d, o)[0]

    def s(self, p):
        if not p: return ''
        n = self.h(p)
        return self.d[p + 2:p + 2 + n].decode('utf8', 'replace')

    def dic(self, p):
        n = struct.unpack_from('<I', self.d, p + 4)[0]
        return [self.s(self.q(p + 8 + 16 * (i + 1) + 8)) for i in range(n)]

    def item(self, p):
        d = self.d
        t, n = d[p], self.h(p + 2)
        v = p + 0x10
        if t == 1:
            names = self.dic(self.q(p + 8))
            return {names[i]: self.item(self.q(v + 8 * i)) for i in range(n)}
        if t == 2: return struct.unpack_from('<i', d, v)[0]
        if t == 3: return bool(struct.unpack_from('<I', d, v)[0] & 1)
        if t == 4: return round(struct.unpack_from('<f', d, v)[0], 4)
        if t in (0, 5, 6): return self.s(self.q(v))
        if t == 7: return list(struct.unpack_from('<%di' % n, d, v))
        if t == 8: return [bool(x & 1) for x in struct.unpack_from('<%dI' % n, d, v)]
        if t == 9: return [round(x, 4) for x in struct.unpack_from('<%df' % n, d, v)]
        if t in (10, 11): return [self.s(self.q(v + 8 * i)) for i in range(n)]
        if t == 12: return '%s/%s' % (self.s(self.q(v)), self.s(self.q(v + 8)))
        return '<type %d>' % t

    def params(self, p): return self.item(p) if p else {}

    def chart(self, c):
        h = self.h
        na, _, _, ne, nent = (h(c + 0x10 + 2 * i) for i in range(5))
        actors = []
        for i in range(na):
            a = self.q(c + 0x28) + i * 0x38
            nact, nq = h(a + 0x30), h(a + 0x32)
            actors.append({
                'name': self.s(self.q(a)), 'sub': self.s(self.q(a + 8)),
                'actions': [self.s(self.q(self.q(a + 0x18) + 8 * j)) for j in range(nact)],
                'queries': [self.s(self.q(self.q(a + 0x20) + 8 * j)) for j in range(nq)]})
        events = []
        for i in range(ne):
            e = self.q(c + 0x30) + i * 0x30
            t = self.d[e + 8]
            ev = {'name': self.s(self.q(e)), 'type': t}
            a, b, x = h(e + 0xA), h(e + 0xC), h(e + 0xE)
            if t == ACTION:
                ev.update(next=a, actor=actors[b]['name'], call=actors[b]['actions'][x], params=self.params(self.q(e + 0x10)))
            elif t == SWITCH:
                cp = self.q(e + 0x18)
                ev.update(actor=actors[b]['name'], call=actors[b]['queries'][x], params=self.params(self.q(e + 0x10)),
                          cases=[(struct.unpack_from('<I', self.d, cp + 8 * k)[0], h(cp + 8 * k + 4)) for k in range(a)])
            elif t == FORK:
                fp = self.q(e + 0x10)
                ev.update(join=b, forks=[h(fp + 2 * k) for k in range(a)])
            elif t == JOIN:
                ev.update(next=a)
            elif t == SUBFLOW:
                ev.update(next=a, params=self.params(self.q(e + 0x10)),
                          flow=self.s(self.q(e + 0x18)), entry=self.s(self.q(e + 0x20)))
            elif t == CALLSWITCH:
                cp = self.q(e + 0x18)
                ev.update(params=self.params(self.q(e + 0x10)), flow=self.s(self.q(e + 0x20)), entry=self.s(self.q(e + 0x28)),
                          cases=[(struct.unpack_from('<I', self.d, cp + 8 * k)[0], h(cp + 8 * k + 4)) for k in range(a)])
            elif t == RETURN:
                ev.update(value=struct.unpack_from('<I', self.d, e + 0xC)[0])
            events.append(ev)
        names = self.dic(self.q(c + 0x38))
        entries = {}
        for i in range(nent):
            ep = self.q(c + 0x40) + i * 0x20
            entries[names[i]] = h(ep + 0x1C)
        return {'name': self.s(self.q(c + 0x20)), 'actors': actors, 'events': events, 'entries': entries}


NONE = 0xFFFF


def fmt_params(p):
    return ', '.join('%s=%s' % (k, v) for k, v in p.items() if v not in ('', None))


def render(chart):
    """Readable listing: each entry point walked as a tree; shared events are printed once and referenced."""
    ev = chart['events']
    out, done = [], set()

    def walk(i, ind, stop=None):
        while i != NONE and i != stop:
            if i in done:
                out.append('%s-> goto [%d] %s' % (ind, i, ev[i]['name'])); return
            done.add(i)
            e = ev[i]; t = e['type']
            tag = '%s[%d] ' % (ind, i)
            if t == ACTION:
                out.append('%s%s.%s(%s)' % (tag, e['actor'], e['call'], fmt_params(e['params'])))
                i = e['next']
            elif t == SUBFLOW:
                out.append('%sCALL %s<%s>(%s)' % (tag, e['flow'] or '(this)', e['entry'], fmt_params(e['params'])))
                i = e['next']
            elif t == SWITCH:
                out.append('%sIF %s.%s(%s)' % (tag, e['actor'], e['call'], fmt_params(e['params'])))
                yn = ('Choice' not in e['call'] and 'Random' not in e['call'] and {v for v, _ in e['cases']} <= {0, 1})
                for val, tgt in e['cases']:
                    out.append('%s  %s:' % (ind, ('YES' if val == 0 else 'NO') if yn else 'case %d' % val))
                    walk(tgt, ind + '    ')
                return
            elif t == CALLSWITCH:
                out.append('%sCALL %s<%s>(%s) and branch on its result' % (tag, e['flow'] or '(this)', e['entry'], fmt_params(e['params'])))
                for val, tgt in e['cases']:
                    out.append('%s  result #%08x:' % (ind, val)); walk(tgt, ind + '    ')
                return
            elif t == RETURN:
                out.append('%sRETURN result #%08x' % (tag, e['value'])); return
            elif t == FORK:
                out.append('%sPARALLEL' % tag)
                for k, f in enumerate(e['forks']):
                    out.append('%s  branch %d:' % (ind, k)); walk(f, ind + '    ', e['join'])
                i = e['join']
            elif t == JOIN:
                i = e['next']

    for name, start in chart['entries'].items():
        out.append('\n== entry %s' % name)
        walk(start, '  ')
    return '\n'.join(out)


NOISE = ('Camera', 'Sound', 'Fade', 'Wait', 'Participate', 'Ducking', 'DoF', 'LookAt', 'Look', 'Turn', 'MoveTo',
         'MoveAt', 'Warp', 'PlayAS', 'Emotion', 'Lod', 'Balloon', 'Weather', 'SetTime', 'HeartGauge', 'Heal',
         'Bgm', 'StartWith', 'Unequip', 'DoNothing', 'BeforehandLoad', 'CloseMessage', 'ShowChallengeProgressUI',
         'Stop', 'Anim', 'Effect', 'Model', 'Cloth', 'Navi', 'Sync', 'Shake', 'Rumble', 'Position', 'Request')
NOISE_FLOWS = ('Common_Camera', 'InitTalk', 'Common<AirStartUp>', 'NaviEventCommon')


def say_action(e):
    """One plain-English line for an action, or None when it is presentation only."""
    c, p = e['call'], e['params']
    if c == 'EventTransition':
        ev = p.get('EventName', '?')
        return ('plays cutscene %s' if ev.startswith('Dm') else 'starts event %s') % ev
    if c.startswith('EventTriggerSetGameData'):
        v = p.get('Value')
        return 'sets %s = %s' % (p.get('GameDataName'), str(v).lower() if isinstance(v, bool) else v)
    if c == 'EventTriggerAddOrSubGameDataInt':
        return 'adds %s to %s' % (p.get('Value'), p.get('GameDataName'))
    if c == 'EventExecuteProgressChallengeStep':
        s = p.get('StepName')
        return ('story: Step_%s -> %s' % (p.get('ChallengeName'), s)) if s else 'story: starts quest %s' % p.get('ChallengeName')
    if c == 'EventExecuteRollbackChallengeStep':
        return 'story: Step_%s rolled back to %s' % (p.get('ChallengeName'), p.get('ChallengeStep'))
    if c == 'EventReserveBancChange':
        b = p.get('BootEventName')
        return 'moves you to area %s%s' % (p.get('NextBanc'), ', then starts %s' % b if b else '')
    if c == 'EventTriggerSetEventBool':
        return 'signals the scene logic (EventBool=%s)' % str(p.get('Bool')).lower()
    if c == 'EventTalk': return 'dialogue'
    if 'Pouch' in c or 'GetItem' in c or 'Item' in c and 'Show' not in c:
        keep = ', '.join('%s=%s' % kv for kv in p.items() if kv[1] not in ('', None, 0, False, -1) and 'Wait' not in kv[0])
        return 'item: %s(%s)' % (c.replace('EventTrigger', '').replace('Event', ''), keep)
    if any(k in c for k in NOISE): return None
    keep = ', '.join('%s=%s' % kv for kv in p.items() if kv[1] not in ('', None) and kv[0] != 'IsWaitEnd')
    return '%s %s(%s)' % (e['actor'], c.replace('EventTrigger', '').replace('Event', ''), keep[:120])


def say_query(e):
    c, p = e['call'], e['params']
    if c == 'EventQueryIsGameDataBool':
        return '%s is true' % p.get('GameDataName'), '%s is false' % p.get('GameDataName')
    if c == 'EventQueryIsGameDataBoolExp': return p.get('GameDataName'), 'NOT %s' % p.get('GameDataName')
    if c == 'EventQueryHavePlayedEvent':
        return 'event %s was already played' % p.get('EventName'), 'event %s was NOT played yet' % p.get('EventName')
    if c == 'EventQueryIsRecommendedMelody': return 'the player played the right song', 'the player played a wrong song'
    if c == 'EventQueryIsGameDataInt': return 'value of %s' % p.get('GameDataName')
    if 'TalkChoice' in c: return 'the player\'s answer'
    if 'RandomChoice' in c: return 'random pick'
    keep = ', '.join('%s=%s' % kv for kv in p.items() if kv[1] not in ('', None))
    return '%s %s(%s)' % (e['actor'], c.replace('EventQuery', ''), keep[:100])


def plain(chart, start):
    """Plain-English steps for one entry point (presentation-only actions hidden)."""
    ev = chart['events']
    budget = [400]

    def walk(i, stop=None, path=frozenset()):
        lines = []
        while i != NONE and i != stop:
            budget[0] -= 1
            if i in path or budget[0] < 0:
                lines.append('(loops back)' if i in path else '…'); break
            path = path | {i}
            e = ev[i]; t = e['type']
            if t == ACTION:
                s = say_action(e)
                if s and not (s == 'dialogue' and lines and lines[-1] == 'dialogue'): lines.append(s)
                i = e['next']
            elif t == SUBFLOW:
                tgt = '%s<%s>' % (e['flow'] or chart['name'], e['entry'])
                if not any(n in tgt for n in NOISE_FLOWS): lines.append('runs sub-event %s' % tgt)
                i = e['next']
            elif t == SWITCH:
                q = say_query(e)
                q, neg = q if isinstance(q, tuple) else (q, 'NOT ' + q)
                yn = ('Choice' not in e['call'] and 'Random' not in e['call'] and {v for v, _ in e['cases']} <= {0, 1})
                branches = [(v, walk(tgt, None, path)) for v, tgt in e['cases']]
                if not any(b for _, b in branches): break
                shown = 0
                for v, b in branches:
                    if yn and b is not None and not b and len(branches) == 2: continue
                    if yn: head = 'otherwise:' if shown else 'if %s:' % (q if v == 0 else neg)
                    else: head = 'if %s = %d:' % (q, v)
                    shown += 1
                    lines.append(head)
                    lines += ['   ' + x for x in (b or ['(nothing)'])]
                break
            elif t == CALLSWITCH:
                tgt = '%s<%s>' % (e['flow'] or chart['name'], e['entry'])
                lines.append('runs check %s, then depending on its answer:' % tgt)
                for v, b in [(v, walk(tg, None, path)) for v, tg in e['cases']]:
                    lines.append('   answer #%08x:' % v)
                    lines += ['      ' + x for x in (b or ['(nothing)'])]
                break
            elif t == RETURN:
                lines.append('answers #%08x' % e['value']); break
            elif t == FORK:
                for f in e['forks']: lines += walk(f, e['join'], path)
                i = e['join']
            elif t == JOIN:
                i = e['next']
        return lines

    return walk(start)
