"""Spawn points (StartPos actors) per map -> spawns.json."""
from common import HERE, romfs_path, decompress
import glob, json, math, os, sys

from byml_lite import Byml

ROMFS = romfs_path()


def yaw(rot):
    """Heading of an XYZ euler rotation: (pi, y, pi) is the same facing as (0, pi - y, 0)."""
    if not rot: return 0.0
    rx, ry, rz = rot
    if abs(abs(rx) - math.pi) < 0.01 and abs(abs(rz) - math.pi) < 0.01: ry = math.pi - ry
    return math.atan2(math.sin(ry), math.cos(ry))


def main():
    maps = sorted(os.path.basename(f).split('.')[0]
                  for f in glob.glob(os.path.join(ROMFS, 'Banc', 'GameBancParam', '*.game__banc__GameBancParam.bgyml')))
    out = {}
    for m in maps:
        rows, seen = [], set()
        for part in ('Static', 'Dynamic'):
            for f in glob.glob(os.path.join(ROMFS, 'Banc', '*', '%s_%s.bcett.byml.zs' % (m, part))):
                try: root = Byml(decompress(open(f, 'rb').read())).root
                except Exception: continue
                for a in root.get('Actors', []):
                    if not isinstance(a, dict) or a.get('Gyaml') != 'StartPos' or not a.get('Translate'): continue
                    pos = [round(x, 3) for x in a['Translate']]
                    key = (a.get('Name'), tuple(pos))
                    if key in seen: continue
                    seen.add(key)
                    rows.append({'name': a.get('Name') or '(unnamed)', 'file': part, 'pos': pos,
                                 'yaw': round(yaw(a.get('Rotate')), 4)})
        if rows: out[m] = sorted(rows, key=lambda r: r['name'].lower())
    json.dump(out, open(os.path.join(HERE, 'spawns.json'), 'w', encoding='utf8'), indent=0)
    print(len(out), 'maps,', sum(len(v) for v in out.values()), 'spawn points')


if __name__ == '__main__':
    main()
