# OoT26 Save Editor

Save editor for The Legend of Zelda: Ocarina of Time (Nintendo Switch 2). Tested on version 1.1.1.

## Features

- Edit every flag in `progress.sav`: booleans, numbers, enums, strings, positions.
- Tabs for player, items, bottles, songs, quest items, dungeons, story progress, chests, Gold Skulltulas, rooms and events.
- Set the map and spawn point Link loads at.
- Compare two saves and copy values between them.
- Command-line tool for listing, reading, writing and diffing flags.

With reference data built from a romfs dump:

- Triggers & events: what sets, checks or triggers a flag, story step, event or cutscene.
- Enemies & Link stats: health, damage multipliers, attacks, Link's movement parameters.
- Spawn points for every map.

## Requirements

Python 3.10+ with Tkinter.

```
pip install -r requirements.txt
```

## Usage

```
python ootsave_gui.py [progress.sav]
```

or `OoT Save Editor.bat` on Windows. Close the game before editing a save. The original file is kept as `.bak`.

```
python ootsave.py list progress.sav -f IsGet -s
python ootsave.py set progress.sav IsGet.Item_Arrow_Light=true
python ootsave.py diff old.sav new.sav
```

## Reference data

Optional. Built from your own romfs dump:

```
python tools/build_all.py <romfs folder>
```
