"""Render every romfs/Logic/*.ainb to logic/<name>.txt (technical) and logic_rules.json (plain rules),
with the scene actors that use each module."""
from common import HERE, romfs_path
import glob, json, os, sys

import ainb_render
import ainb_rules
import byml_lite

ROMFS = romfs_path()
OUT = os.path.join(HERE, 'logic')


def logic_users(romfs):
    """logic module basename -> [(banc file, [actor instance ids])] from every bcett AiGroups table."""
    import glob, os
    from common import decompress
    from byml_lite import Byml
    res = {}
    for f in glob.glob(os.path.join(romfs, 'Banc', '**', '*.bcett.byml.zs'), recursive=True):
        try: root = Byml(decompress(open(f, 'rb').read())).root
        except Exception: continue
        if not isinstance(root, dict): continue
        acts = {a.get('Hash'): a for a in root.get('Actors', []) if isinstance(a, dict)}
        for g in root.get('AiGroups', []):
            lg = g.get('Logic', '')
            if not lg: continue
            base = os.path.basename(lg)
            if base.endswith('.ain'): base = base[:-4]
            refs = {}
            for r in g.get('References', []):
                a = acts.get(r.get('Reference'), {})
                dyn = a.get('Dynamic') or {}
                refs[r.get('Id', '')] = {'gyaml': a.get('Gyaml', ''), 'dyn': dyn,
                                         'pos': [round(x, 1) for x in a.get('Translate', [])][:3]}
            res.setdefault(base, []).append((os.path.basename(f).split('.')[0], refs))
    return res


def dyn_text(v):
    return ' {%s}' % ', '.join('%s=%s' % kv for kv in v['dyn'].items()) if v['dyn'] else ''


def main():
    os.makedirs(OUT, exist_ok=True)
    users = logic_users(ROMFS)
    rules = []
    ok = bad = 0
    for p in sorted(glob.glob(os.path.join(ROMFS, 'Logic', '**', '*.ainb'), recursive=True)):
        base = os.path.basename(p)[:-len('.ainb')]
        scenes = users.get(base, [])
        refs = {}
        for _, r in scenes: refs.update(r)
        try:
            d = ainb_render.load(open(p, 'rb').read())
            txt = ainb_render.Renderer(d).render()
            for r in ainb_rules.Rules(d, refs).rules():
                r['module'] = base; r['scenes'] = sorted({s for s, _ in scenes})
                rules.append(r)
            ok += 1
        except Exception as e:
            txt = '(parse error: %s)' % e; bad += 1
        head = ''
        for f, r in scenes:
            head += '# used in scene %s\n' % f
            for k, v in r.items():
                head += '#   %s = %s%s\n' % (k, v['gyaml'], dyn_text(v))
                if v['dyn']: txt = txt.replace('InstanceName=%s' % k, 'InstanceName=%s%s' % (k, dyn_text(v)))
        open(os.path.join(OUT, base + '.txt'), 'w', encoding='utf8').write(head + txt + '\n')
    json.dump(rules, open(os.path.join(HERE, 'logic_rules.json'), 'w', encoding='utf8'), ensure_ascii=False, default=str)
    print('rendered %d, failed %d, %d rules' % (ok, bad, len(rules)))


if __name__ == '__main__':
    main()
