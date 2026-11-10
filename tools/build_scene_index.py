"""Index scene (Banc) actors that carry parameters: scene_index.json = [{scene, actor, name, id, params, logic}]."""
from common import HERE, romfs_path, decompress
import glob, json, os, sys

from byml_lite import Byml

ROMFS = romfs_path()


def main():
    out = []
    for f in sorted(glob.glob(os.path.join(ROMFS, 'Banc', '**', '*.bcett.byml.zs'), recursive=True)):
        try: root = Byml(decompress(open(f, 'rb').read())).root
        except Exception: continue
        if not isinstance(root, dict): continue
        scene = os.path.basename(f).split('.')[0]
        logic = {}
        for g in root.get('AiGroups', []):
            lg = os.path.basename(g.get('Logic', '')).replace('.ain', '')
            for r in g.get('References', []): logic.setdefault(r.get('Reference'), []).append(lg)
        for a in root.get('Actors', []):
            if not isinstance(a, dict): continue
            dyn = a.get('Dynamic') or {}
            if not dyn and a.get('Hash') not in logic: continue
            out.append({'scene': scene, 'actor': a.get('Gyaml', ''), 'name': a.get('Name', ''), 'id': a.get('Hash'),
                        'pos': [round(x, 1) for x in a.get('Translate', [])],
                        'params': {k: v for k, v in dyn.items()}, 'logic': logic.get(a.get('Hash'), [])})
    json.dump(out, open(os.path.join(HERE, 'scene_index.json'), 'w', encoding='utf8'), default=str, ensure_ascii=False)
    print(len(out), 'actors')


if __name__ == '__main__':
    main()
