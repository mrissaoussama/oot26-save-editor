"""Build all reference data from a romfs dump: python tools/build_all.py <romfs folder>"""
import datetime, glob, json, os, re, subprocess, sys

from common import HERE, romfs_path

STEPS = ['build_event_index.py', 'build_logic_dump.py', 'build_scene_index.py', 'build_actor_stats.py',
         'build_spawns.py', 'build_catchable.py', 'build_item_events.py']
BUILD_IDS = {'33FA6C2C23848282A77E8B88A0A93F4887C55920': '1.0.0', 'E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348': '1.1.1'}


def game_info(romfs):
    """Game version from the newest Product.<n> tag in the dump, and the build id of exefs/main next to it."""
    tags = [int(m.group(1)) for f in glob.glob(os.path.join(romfs, '**', '*Product.*'), recursive=True)
            for m in [re.search(r'Product\.(\d{3})', os.path.basename(f))] if m]
    info = {}
    if tags:
        t = str(max(tags))
        info['game_version'] = '%s.%s.%s' % (t[0], t[1], t[2])
    main = os.path.join(os.path.dirname(os.path.abspath(romfs)), 'exefs', 'main')
    if os.path.exists(main):
        head = open(main, 'rb').read(0x60)
        if head[:4] == b'NSO0':
            bid = head[0x40:0x54].hex().upper()
            info['main_build_id'] = bid
            if bid in BUILD_IDS: info['game_version'] = BUILD_IDS[bid]
    return info


def main():
    romfs = romfs_path()
    here = os.path.dirname(os.path.abspath(__file__))
    for step in STEPS:
        print('==', step, flush=True)
        args = [sys.executable, os.path.join(here, step)] + ([] if step == 'build_item_events.py' else [romfs])
        if subprocess.call(args) != 0: sys.exit('%s failed' % step)
    info = game_info(romfs)
    info['built'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    json.dump(info, open(os.path.join(HERE, 'data_info.json'), 'w', encoding='utf8'), indent=1)
    print('game version:', info.get('game_version', 'unknown'), flush=True)


if __name__ == '__main__':
    main()
