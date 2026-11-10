"""Actors that can be caught in a bottle -> catchable.json."""
from common import HERE, romfs_path, decompress
import json, os, sys
from multiprocessing import Pool

from build_actor_stats import sarc

ROMFS = romfs_path()
MARKS = (('Insert_Bottle', 'bottle target'), ('PouchContentParam/InBottle', 'in-bottle item'),
         ('CaptureActorCommon', 'capture component'), ('LifeParam/CaptureCommon', 'capture component'))


def check(fn):
    try: files = sarc(decompress(open(os.path.join(ROMFS, 'Pack', 'Actor', fn), 'rb').read()))
    except Exception: return None
    reasons = sorted({why for p in files for mark, why in MARKS if mark in p})
    return (fn[:-len('.pack.zs')], ', '.join(reasons)) if reasons else None


def main():
    packs = [f for f in os.listdir(os.path.join(ROMFS, 'Pack', 'Actor')) if f.endswith('.pack.zs')]
    with Pool() as p:
        res = dict(r for r in p.map(check, packs, chunksize=32) if r)
    json.dump(res, open(os.path.join(HERE, 'catchable.json'), 'w', encoding='utf8'), indent=0, sort_keys=True)
    print(len(res), 'catchable actors')


if __name__ == '__main__':
    main()
