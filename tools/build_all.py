"""Build all reference data from a romfs dump: python tools/build_all.py <romfs folder>"""
import os, subprocess, sys

from common import romfs_path

STEPS = ['build_event_index.py', 'build_logic_dump.py', 'build_scene_index.py', 'build_actor_stats.py',
         'build_spawns.py', 'build_catchable.py', 'build_item_events.py']


def main():
    romfs = romfs_path()
    here = os.path.dirname(os.path.abspath(__file__))
    for step in STEPS:
        print('==', step, flush=True)
        args = [sys.executable, os.path.join(here, step)] + ([] if step == 'build_item_events.py' else [romfs])
        if subprocess.call(args) != 0: sys.exit('%s failed' % step)


if __name__ == '__main__':
    main()
