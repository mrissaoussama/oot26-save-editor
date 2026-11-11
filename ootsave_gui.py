#!/usr/bin/env python3
"""Ocarina of Time (Switch 2) save editor GUI: view/edit flags, items, equipment; compare saves."""
import json, math, os, re, sys
import io
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import subprocess
import threading
import queue
import webbrowser

import ootrefs
import ootstats
import ootdrops

APP_NAME = 'OoT26 Save Editor'
APP_VERSION = '1.0.0'
APP_AUTHOR = 'mrissaoussama'
APP_URL = 'https://github.com/mrissaoussama/oot26-save-editor'
HERE = os.path.dirname(os.path.abspath(__file__))
NOT_BUILT = 'Reference data not built. Use "Build reference data…" with a romfs dump, or run:\n  python tools/build_all.py <romfs folder>'


def stats_intro():
    if not ootstats.available(): return NOT_BUILT
    return ('Game balance values read from the romfs actor packs (read only: changing them needs a romfs mod).\n\n'
            'Show: Link = health, jump heights, roll/swim speeds, healing, attack multipliers, weapon damage;\n'
            'Enemies / Bosses = health, hits needed per sword, damage they take per type, damage their attacks do;\n'
            'Weapons & items = base damage, guard break, range; Projectiles = arrows, fireballs, beams.\n\n'
            'Units: 4 life = 1 heart (the save uses 16 = 1 heart). Damage = base attack x multiplier. Distances in metres, times in frames.\n'
            'Names shown as #number are hashes whose original text is not in the game data.')


def drops_intro():
    if not ootdrops.available(): return NOT_BUILT
    return ('Where items drop from: chests, pots, grass, rocks, enemies, and the drop tables they roll on.\n\n'
            'Show: Items = search an item (e.g. "heart", "rupee", "arrows", "mirror") to see what drops it, where and when;\n'
            'Sources = an enemy or object and what it drops on each map; Drop tables = one table and who uses it;\n'
            'Maps = every fixed and random drop on one map.\n\n'
            'Chance = share of one roll. "Low-resource boost" raises a chance when Link is low on that item.\n'
            'Arrows / Deku Seeds: the same drop gives arrows as adult and seeds as child.\n'
            'Chest flags (IsTreasureBoxOpen.<id>) can be edited in the Chests tab.')


def data_info():
    try: return json.load(open(os.path.join(HERE, 'data_info.json'), encoding='utf8'))
    except (OSError, ValueError): return {}

from ootcore import (ACTOR, BKEY, BY_NAME, EDITABLE, META, NAMES, Save, caption_info, diff,
                     enum_choices, name, storage)

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None

DEFAULT_DIR = os.path.expandvars(r'%APPDATA%\eden\nand\user\save\0000000000000000')

ITEM_NAMES = sorted({m.group(1) for n in NAMES.values() for m in [re.match(r'PouchData\.(.+)\.StockNum$', n)] if m})

# (tab title, regex on full name, prefix stripped for display)
CATEGORIES = [
    ('Player', r'^PlayerStatus\.(?!AssignableItem\.BottleInfo)', 'PlayerStatus.'),
    ('Items & Equipment', r'^PouchData\.', 'PouchData.'),
    ('Bottles', r'BottleInfo\.|^PouchData\.Bottle', ''),
    ('Songs & Quest', r'^IsGet\.Item_(Melody|Medal|Stone|Token)|^PouchData\.Item_(Medal|Stone|Token)', ''),
    ('Acquired (IsGet)', r'^IsGet\.', 'IsGet.'),
    ('Dungeons', r'^DungeonInfo\.', 'DungeonInfo.'),
    ('Story', r'^Step_|^Sequence_|^IsVisitLocation\.', ''),
    ('Chests', r'^IsTreasureBoxOpen\.', 'IsTreasureBoxOpen.'),
    ('World objects', r'ScrubBusiness|GossipStone|ChainLockDoor|DoorKeepOpen|MagicBean|SongOfTimeSymbol|IsOpenHole', ''),
    ('Dungeon rooms', r'^DungeonRoomStep\.', 'DungeonRoomStep.'),
    ('Events & dialogue', r'^HavePlayed|^HaveTalked', ''),
    ('All flags', r'', ''),
]


def fmt(v):
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (list, dict)): return json.dumps(v, ensure_ascii=False)
    return str(v)


def _file_index(path):
    b = os.path.basename(path).lower()
    return next((i for i, f in ((0, 'progress'), (1, 'option'), (2, 'caption'), (3, 'account')) if f in b), 0)


def is_set(v):
    return v not in (False, 0, 0.0, '', [], None, 'Empty', 'None', 'NotReady', '0x00000000')


class FlagTable(ttk.Frame):
    def __init__(self, master, app, pattern, strip):
        super().__init__(master)
        self.app, self.rx, self.strip = app, re.compile(pattern), strip
        bar = ttk.Frame(self); bar.pack(fill='x', pady=4)
        ttk.Label(bar, text='Search').pack(side='left', padx=(4, 2))
        self.q = tk.StringVar(); e = ttk.Entry(bar, textvariable=self.q, width=40); e.pack(side='left')
        self.q.trace_add('write', lambda *a: self.refresh())
        self.only_set = tk.BooleanVar()
        ttk.Checkbutton(bar, text='Only set', variable=self.only_set, command=self.refresh).pack(side='left', padx=8)
        self.named = tk.BooleanVar()
        ttk.Checkbutton(bar, text='Only named', variable=self.named, command=self.refresh).pack(side='left')
        self.extra = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text='Show * not-saved flags', variable=self.extra, command=self.load).pack(side='left', padx=8)
        ttk.Button(bar, text='Visible bools: all off', command=lambda: self.bulk(False)).pack(side='right', padx=4)
        ttk.Button(bar, text='Visible bools: all on', command=lambda: self.bulk(True)).pack(side='right')
        self.count = ttk.Label(bar, foreground='#666'); self.count.pack(side='right', padx=10)
        cols = ('stored', 'value', 'type', 'info')
        frame = ttk.Frame(self); frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(frame, columns=cols, selectmode='extended')
        self.tree.heading('#0', text='Flag', command=lambda: self.sort('#0'))
        for c, w in zip(cols, (110, 220, 90, 420)):
            self.tree.heading(c, text=c.capitalize(), command=lambda c=c: self.sort(c))
            self.tree.column(c, width=w, stretch=c == 'info')
        self.tree.column('#0', width=430)
        sb = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.tree.tag_configure('changed', background='#fff3c4')
        self.tree.tag_configure('ro', foreground='#888')
        self.tree.tag_configure('nosave', foreground='#9a6bb5')
        self.tree.bind('<Double-1>', self.edit)
        self.tree.bind('<Return>', self.edit)
        self.tree.bind('<F2>', self.edit)
        self.tree.bind('<space>', self.toggle)
        self.tree.bind('<Control-i>', lambda e: self.where_used())
        self.tree.bind('<Button-3>', self.context_menu)
        self.tree.bind('<MouseWheel>', lambda e: self.close_editor(), add='+')
        self.tree.bind('<Configure>', lambda e: self.close_editor(), add='+')
        self.rows = []
        self.sort_key, self.sort_rev = '#0', False
        self.editor = None

    def close_editor(self, commit=False):
        ed, self.editor = self.editor, None
        if not ed: return
        w, h, var = ed
        if commit:
            s = self.app.save
            old = s.get(h)
            try:
                s.set(h, var.get())
            except (ValueError, json.JSONDecodeError) as e:
                w.destroy(); messagebox.showerror('Invalid value', '%s: %s' % (name(h), e)); return
            w.destroy()
            if s.get(h) != old:
                self.app.mark(h); self.app.refresh_all()
            self.tree.focus_set(); self.tree.selection_set(str(h)); self.tree.see(str(h))
        else:
            w.destroy()

    def open_editor(self, h):
        self.close_editor()
        s = self.app.save; t = s.type(h)
        self.tree.see(str(h)); self.update_idletasks()
        box = self.tree.bbox(str(h), 'value')
        if not box: return
        x, y, wd, ht = box
        var = tk.StringVar(value=fmt(s.get(h)))
        choices = (enum_choices(h) if t == 'Enum' else
                   ITEM_NAMES if 'String' in t and re.search(r'Equip|Item', name(h)) else None)
        if choices:
            w = ttk.Combobox(self.tree, textvariable=var, values=choices,
                             state='readonly' if t == 'Enum' else 'normal')
            w.bind('<<ComboboxSelected>>', lambda e: self.close_editor(True))
        else:
            w = ttk.Entry(self.tree, textvariable=var)
            w.select_range(0, 'end')
        w.place(x=x, y=y, width=max(wd, 260 if choices else wd), height=ht)
        w.bind('<Return>', lambda e: self.close_editor(True))
        w.bind('<KP_Enter>', lambda e: self.close_editor(True))
        w.bind('<Escape>', lambda e: self.close_editor())
        w.bind('<FocusOut>', lambda e: self.after(150, self._focus_check, w))
        w.focus_set()
        self.editor = (w, h, var)
        if t == 'Enum':
            w.after(30, lambda: w.event_generate('<Down>'))

    def _focus_check(self, w):
        if not self.editor or self.editor[0] is not w: return
        f = str(self.tk.call('focus'))
        if f.startswith(str(w)) or 'popdown' in f: return
        self.close_editor(commit=not isinstance(w, ttk.Combobox) or w.cget('state') != 'readonly')

    def load(self):
        s = self.app.save
        self.rows = []
        if not s: self.refresh(); return
        hs = list(s.entries)
        if self.extra.get():
            hs += [h for h, m in META.items() if h not in s.entries and storage(h, s) != 'progress.sav'
                   and m[1] != _file_index(s.path)]
        for h in hs:
            n = name(h)
            if self.rx.pattern and not self.rx.search(n): continue
            disp = n[len(self.strip):] if self.strip and n.startswith(self.strip) else n
            self.rows.append((h, disp.removesuffix('.StockNum')))
        self.refresh()

    def refresh(self):
        s = self.app.save
        if self.editor: self.close_editor()
        self.tree.delete(*self.tree.get_children())
        if not s: return
        q = self.q.get().lower()
        rows = []
        for h, disp in self.rows:
            info = ACTOR.get(h, '')
            if q and q not in disp.lower() and q not in info.lower() and q not in '%08x' % h: continue
            if self.named.get() and disp.startswith('?'): continue
            where = storage(h, s)
            if where == 'file':
                v = s.get(h); t = s.type(h); stored = 'saved'
                if self.only_set.get() and not is_set(v): continue
                rows.append((h, disp, stored, fmt(v), t, info, False))
            else:
                if self.only_set.get(): continue
                m = META[h]
                stored = {'runtime': '* runtime', 'computed': '* computed'}.get(where, '→ ' + where)
                rows.append((h, '* ' + disp, stored, '(default %s)' % fmt(m[3]) if m[3] is not None else '', m[0], info, True))
        k = {'#0': 1, 'stored': 2, 'value': 3, 'type': 4, 'info': 5}[self.sort_key]
        rows.sort(key=lambda r: r[k].lower(), reverse=self.sort_rev)
        for h, disp, stored, v, t, info, nosave in rows:
            tags = ('nosave',) if nosave else ('changed',) if h in self.app.changed else ('ro',) if t not in EDITABLE else ()
            self.tree.insert('', 'end', iid=str(h), text=disp, values=(stored, v[:300], t, info), tags=tags)
        extra = sum(1 for r in rows if r[6])
        self.count.config(text='%d flags (%d saved, %d * not in this file)' % (len(rows), len(rows) - extra, extra))

    def sort(self, col):
        self.sort_rev = not self.sort_rev if self.sort_key == col else False
        self.sort_key = col; self.refresh()

    def selected(self):
        return [int(i) for i in self.tree.selection() if int(i) in self.app.save.entries]

    def context_menu(self, e):
        row = self.tree.identify_row(e.y)
        if not row: return
        if row not in self.tree.selection(): self.tree.selection_set(row)
        m = tk.Menu(self, tearoff=0)
        m.add_command(label='Where used / what triggers it   Ctrl+I', command=self.where_used)
        m.add_command(label='Edit   F2', command=self.edit)
        m.add_command(label='Copy name', command=lambda: (self.clipboard_clear(), self.clipboard_append(name(int(row)))))
        m.tk_popup(e.x_root, e.y_root)

    def where_used(self):
        sel = self.tree.selection()
        if sel: self.app.explore(name(int(sel[0])))
        return 'break'

    def explain(self):
        hs = [int(i) for i in self.tree.selection() if int(i) not in self.app.save.entries]
        if not hs: return False
        where = storage(hs[0], self.app.save)
        msg = {'runtime': 'only exists while the game is running. It is never written to a save file, so it cannot be edited here.',
               'computed': 'is a condition computed from other flags at runtime. It is not stored anywhere.'}.get(
               where, 'is stored in %s, not in this file. Open that file to edit it.' % where)
        messagebox.showinfo('Not in this save', '%s %s' % (name(hs[0]), msg))
        return True

    def toggle(self, event=None):
        if not self.selected() and self.explain(): return 'break'
        hs = [h for h in self.selected() if self.app.save.type(h) == 'Bool']
        for h in hs:
            self.app.set(h, not self.app.save.get(h))
        if hs: self.app.refresh_all()
        return 'break'

    def edit(self, event=None):
        sel = self.selected()
        if not sel:
            self.explain(); return
        h = sel[0]; s = self.app.save
        t = s.type(h)
        if t == 'Bool':
            return self.toggle()
        if t not in EDITABLE:
            messagebox.showinfo('Read only', '%s values cannot be edited yet.' % t); return
        self.open_editor(h)

    def bulk(self, value):
        hs = [int(i) for i in self.tree.get_children()
              if int(i) in self.app.save.entries and self.app.save.type(int(i)) == 'Bool']
        if not hs: return
        if not messagebox.askyesno('Bulk change', 'Set %d visible Bool flags to %s?' % (len(hs), value)): return
        for h in hs:
            self.app.set(h, value)
        self.app.refresh_all()


class ActorKeyTable(ttk.Frame):
    """Per-placed-actor flags (Bool64bitKey): a key present in the list means 'set'."""
    def __init__(self, master, app, preset=''):
        super().__init__(master)
        self.app = app
        bar = ttk.Frame(self); bar.pack(fill='x', pady=4)
        ttk.Label(bar, text='Search').pack(side='left', padx=(4, 2))
        self.q = tk.StringVar(value=preset); ttk.Entry(bar, textvariable=self.q, width=40).pack(side='left')
        self.q.trace_add('write', lambda *a: self.refresh())
        self.only_set = tk.BooleanVar()
        ttk.Checkbutton(bar, text='Only set', variable=self.only_set, command=self.refresh).pack(side='left', padx=8)
        ttk.Label(bar, foreground='#666', text='Space/double-click toggles. +0/+2 = the two flags each actor can have.'
                  ).pack(side='left', padx=8)
        self.count = ttk.Label(bar, foreground='#666'); self.count.pack(side='right', padx=10)
        frame = ttk.Frame(self); frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(frame, columns=('value', 'key'), selectmode='extended')
        self.tree.heading('#0', text='Actor @ scene'); self.tree.column('#0', width=700)
        self.tree.heading('value', text='Set'); self.tree.column('value', width=80)
        self.tree.heading('key', text='Key'); self.tree.column('key', width=200)
        sb = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.tree.tag_configure('changed', background='#fff3c4')
        self.tree.bind('<Double-1>', self.toggle); self.tree.bind('<space>', self.toggle)
        self.rows = sorted(((int(k, 16), v) for k, v in BKEY.items()), key=lambda r: r[1])

    def load(self):
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        s = self.app.save
        if not s or s.bkey_flag() is None: self.count.config(text='no actor list in this file'); return
        keys = s.bkeys(); q = self.q.get().lower(); n = 0
        known = {k for k, _ in self.rows}
        rows = self.rows + [(k, '(unknown actor)') for k in keys if k not in known]
        for k, desc in rows:
            on = k in keys
            if q and q not in desc.lower() and q not in '%x' % k: continue
            if self.only_set.get() and not on: continue
            self.tree.insert('', 'end', iid='k%d' % k, text=desc, values=('true' if on else 'false', '0x%x' % k),
                             tags=('changed',) if ('k', k) in self.app.changed else ())
            n += 1
        self.count.config(text='%d actors, %d set in save' % (n, len(keys)))

    def toggle(self, event=None):
        s = self.app.save
        try:
            for i in self.tree.selection():
                k = int(i[1:]); s.set_bkey(k, k not in s.bkeys()); self.app.mark(('k', k))
        except ValueError as e:
            messagebox.showerror('Actor flags', str(e))
        self.app.refresh_all()
        return 'break'


def load_thumb(jpeg, width):
    if not jpeg or Image is None: return None
    im = Image.open(io.BytesIO(jpeg))
    im.thumbnail((width, width))
    return ImageTk.PhotoImage(im)


def fmt_time(sec):
    sec = int(sec or 0)
    return '%d:%02d:%02d' % (sec // 3600, sec // 60 % 60, sec % 60)


def fmt_date(d):
    try: return '%04d-%02d-%02d %02d:%02d' % (d['Date.Year'], d['Date.Month'], d['Date.Day'], d['Date.Hour'], d['Date.Minute'])
    except (KeyError, TypeError): return ''


def slot_caption(folder):
    p = os.path.join(folder, 'caption.sav')
    if not os.path.exists(p): return None, {}
    try: return caption_info(p)
    except (OSError, ValueError, struct.error): return None, {}


class SlotPicker(tk.Toplevel):
    """Grid of save slots with screenshot, location, date and hearts."""
    def __init__(self, master, root_dir):
        super().__init__(master)
        self.title('Choose a save slot'); self.transient(master)
        self.result = None; self.images = []
        top = ttk.Frame(self); top.pack(fill='x', padx=10, pady=8)
        self.dir = tk.StringVar(value=root_dir)
        ttk.Label(top, text='Folder').pack(side='left')
        ttk.Entry(top, textvariable=self.dir, width=90).pack(side='left', padx=6, fill='x', expand=True)
        ttk.Button(top, text='Browse...', command=self.browse).pack(side='left')
        ttk.Button(top, text='Open other file...', command=self.other).pack(side='left', padx=6)
        self.grid_frame = ttk.Frame(self); self.grid_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.fill()
        self.grab_set(); self.wait_window()

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.dir.get(), parent=self)
        if d: self.dir.set(d); self.fill()

    def other(self):
        p = filedialog.askopenfilename(initialdir=self.dir.get(), parent=self,
                                       filetypes=[('Saves', '*.sav'), ('All', '*.*')])
        if p: self.result = p; self.destroy()

    @staticmethod
    def find_root(d):
        if os.path.basename(d).startswith('slot_'): d = os.path.dirname(d)
        if any(n.startswith('slot_') for n in os.listdir(d)): return d
        for dp, dn, fn in os.walk(d):
            if any(n.startswith('slot_') for n in dn): return dp
        return d

    def fill(self):
        for w in self.grid_frame.winfo_children(): w.destroy()
        self.images = []
        d = self.dir.get()
        if not os.path.isdir(d):
            ttk.Label(self.grid_frame, text='Folder not found').pack(); return
        d = self.find_root(d); self.dir.set(d)
        slots = sorted(n for n in os.listdir(d)
                       if n.startswith('slot_') and os.path.isfile(os.path.join(d, n, 'progress.sav')))
        if not slots:
            ttk.Label(self.grid_frame, text='No slot_NN/progress.sav here').pack(); return
        for i, slot in enumerate(slots):
            folder = os.path.join(d, slot)
            jpeg, c = slot_caption(folder)
            card = ttk.Frame(self.grid_frame, relief='ridge', borderwidth=2, padding=6)
            card.grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky='n')
            img = load_thumb(jpeg, 300); self.images.append(img)
            pick = lambda e=None, f=folder: self.choose(f)
            if img:
                lab = ttk.Label(card, image=img, cursor='hand2'); lab.pack(); lab.bind('<Button-1>', pick)
            ttk.Label(card, text='%s   %s' % (slot, c.get('LocationName', '')),
                      font=('Segoe UI', 10, 'bold')).pack(anchor='w')
            hearts = '%g/%g hearts' % (c.get('Life', 0) / 16, c.get('MaxLife', 0) / 16) if c.get('MaxLife') else ''
            ttk.Label(card, text='%s   %s   %s rupees%s' % (fmt_date(c), hearts, c.get('CurrentRupee', '?'),
                      '   autosave' if c.get('IsAutoSave') else ''), foreground='#555').pack(anchor='w')
            ttk.Button(card, text='Open', command=pick).pack(anchor='e', pady=(4, 0))

    def choose(self, folder):
        self.result = os.path.join(folder, 'progress.sav'); self.destroy()


class Overview(ttk.Frame):
    STATS = [('Location', 'Sequence_CurrentBanc'), ('Life', 'PlayerStatus.Life'), ('Max life', 'PlayerStatus.MaxLife'),
             ('Magic', 'PlayerStatus.MP'), ('Max magic', 'PlayerStatus.MPMax'), ('Rupees', 'PlayerStatus.CurrentRupee'),
             ('Wallet limit', '?f80f8077.Rupee'), ('Heart pieces', 'PouchData.Obj_Heart_Piece.StockNum'),
             ('Gold Skulltula tokens', 'PouchData.Item_Token_Gold.StockNum'), ('Play time', '?e7162146.PlayTime'),
             ('Chests opened', '?e7162146.TreasureBoxCount'), ('Enemies defeated', '?e7162146.DefeatTotal'),
             ('Sword', 'PlayerStatus.EquipWeapon'), ('Shield', 'PlayerStatus.EquipShield'),
             ('Tunic', 'PlayerStatus.EquipArmor'), ('Boots', 'PlayerStatus.EquipBoot'),
             ('Ocarina', 'PlayerStatus.EquipOcarina'), ('Strength', 'PlayerStatus.LiftGrade')]

    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app; self.img = None
        self.pic = ttk.Label(self); self.pic.grid(row=0, column=0, rowspan=2, sticky='nw', padx=(0, 16))
        self.cap = ttk.Label(self, justify='left', font=('Segoe UI', 10)); self.cap.grid(row=0, column=1, sticky='nw')
        self.stats = ttk.Frame(self); self.stats.grid(row=1, column=1, sticky='nw', pady=(12, 0))
        self.songs = ttk.Label(self, justify='left', wraplength=1100, foreground='#333')
        self.songs.grid(row=2, column=0, columnspan=2, sticky='nw', pady=(16, 0))
        self.lookup = {}

    def load(self):
        s = self.app.save
        if not s: return
        self.lookup = {name(h): h for h in s.entries}
        jpeg, c = slot_caption(os.path.dirname(s.path))
        self.img = load_thumb(jpeg, 640)
        self.pic.config(image=self.img or '', text='' if self.img else '(no caption.sav screenshot)')
        lines = ['Slot card (caption.sav)']
        if c:
            lines += ['  Location: %s' % c.get('LocationName', ''),
                      '  Saved: %s%s' % (fmt_date(c), '  (autosave)' if c.get('IsAutoSave') else ''),
                      '  Hearts %g/%g   Magic %s/%s   Rupees %s   Tokens %s   Game cleared: %s' % (
                          c.get('Life', 0) / 16, c.get('MaxLife', 0) / 16, c.get('MP'), c.get('MPMax'),
                          c.get('CurrentRupee'), c.get('GoldToken'), 'yes' if c.get('IsClear') else 'no'),
                      '  (the slot card is a separate file; editing progress.sav does not update it)']
        else:
            lines.append('  not found next to this file')
        self.cap.config(text='\n'.join(lines))
        self.refresh()

    def refresh(self):
        for w in self.stats.winfo_children(): w.destroy()
        s = self.app.save
        if not s: return
        ttk.Label(self.stats, text='This save (progress.sav)', font=('Segoe UI', 10, 'bold')
                  ).grid(row=0, column=0, columnspan=2, sticky='w')
        for i, (lab, key) in enumerate(self.STATS, 1):
            h = self.lookup.get(key)
            if h is None: continue
            v = s.get(h)
            if key.endswith('PlayTime'): v = fmt_time(v)
            elif key in ('PlayerStatus.Life', 'PlayerStatus.MaxLife'): v = '%s  (%g hearts)' % (v, v / 16)
            ttk.Label(self.stats, text=lab, foreground='#555').grid(row=i, column=0, sticky='w', padx=(0, 12))
            ttk.Label(self.stats, text=fmt(v) or '-').grid(row=i, column=1, sticky='w')
        got = [name(h)[len('IsGet.Item_'):] for h in s.entries
               if re.match(r'IsGet\.Item_(Melody|Medal|Stone)_', name(h)) and s.get(h)]
        self.songs.config(text='Songs / medallions / stones obtained: ' + (', '.join(sorted(got)) or 'none'))


class Explorer(ttk.Frame):
    """Search any flag, story step (Step_*), event id or cutscene and show what sets, checks or triggers it."""
    def __init__(self, master, app, src=ootrefs, kind='Events', raw_text='Technical details', intro=None):
        super().__init__(master)
        self.app = app; self.history = []; self.src = src
        bar = ttk.Frame(self); bar.pack(fill='x', pady=4)
        ttk.Button(bar, text='◀ Back', command=self.back).pack(side='left', padx=4)
        ttk.Label(bar, text='Show').pack(side='left', padx=(8, 2))
        self.kind = tk.StringVar(value=kind)
        kb = ttk.Combobox(bar, textvariable=self.kind, values=src.KINDS, state='readonly', width=14)
        kb.pack(side='left'); kb.bind('<<ComboboxSelected>>', lambda e: self.suggest())
        ttk.Label(bar, text='Search').pack(side='left', padx=(8, 2))
        self.q = tk.StringVar(); e = ttk.Entry(bar, textvariable=self.q, width=50); e.pack(side='left')
        e.bind('<Return>', lambda ev: self.show(self.q.get()))
        self.q.trace_add('write', lambda *a: self.suggest())
        ttk.Button(bar, text='Show', command=lambda: self.show(self.q.get())).pack(side='left', padx=4)
        self.raw = tk.BooleanVar()
        ttk.Checkbutton(bar, text=raw_text, variable=self.raw,
                        command=lambda: self.history and self.show(self.history[-1], push=False)).pack(side='left', padx=8)
        ttk.Label(bar, text='double-click a name in the report to open it   Ctrl+F find in the report', foreground='#777').pack(side='left', padx=6)
        self.intro = intro
        self.buildbar = ttk.Frame(self)
        ttk.Label(self.buildbar, text='Reference data not built.', foreground='#a33').pack(side='left', padx=(4, 8))
        ttk.Button(self.buildbar, text='Build reference data…', command=app.build_data).pack(side='left')
        # Find bar (Ctrl+F): highlights every match in the report, Enter / Shift+Enter next / previous, Esc closes.
        self.findbar = ttk.Frame(self)
        ttk.Label(self.findbar, text='Find').pack(side='left', padx=(4, 2))
        self.fq = tk.StringVar()
        self.fentry = ttk.Entry(self.findbar, textvariable=self.fq, width=40); self.fentry.pack(side='left')
        ttk.Button(self.findbar, text='▲', width=3, command=lambda: self.find_step(-1)).pack(side='left', padx=(4, 0))
        ttk.Button(self.findbar, text='▼', width=3, command=lambda: self.find_step(1)).pack(side='left')
        self.fcount = ttk.Label(self.findbar, foreground='#666'); self.fcount.pack(side='left', padx=8)
        ttk.Button(self.findbar, text='✕', width=3, command=self.find_close).pack(side='left')
        self.fq.trace_add('write', lambda *a: self.find_all())
        self.fentry.bind('<Return>', lambda e: self.find_step(1))
        self.fentry.bind('<Shift-Return>', lambda e: self.find_step(-1))
        self.fentry.bind('<Escape>', lambda e: self.find_close())
        self.fmatches, self.fpos = [], -1
        pw = ttk.PanedWindow(self, orient='horizontal'); pw.pack(fill='both', expand=True)
        self.pw = pw
        left = ttk.Frame(pw); pw.add(left, weight=1)
        self.count = ttk.Label(left, foreground='#666'); self.count.pack(side='top', anchor='w')
        self.lb = tk.Listbox(left, width=40, activestyle='none'); self.lb.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(left, command=self.lb.yview); sb.pack(side='right', fill='y'); self.lb.config(yscrollcommand=sb.set)
        self.lb.bind('<<ListboxSelect>>', lambda e: self.lb.curselection() and self.show(self.lb.get(self.lb.curselection()[0]), keep_query=True))
        right = ttk.Frame(pw); pw.add(right, weight=4)
        self.txt = tk.Text(right, wrap='word', font=('Consolas', 9), undo=False)
        ys = ttk.Scrollbar(right, command=self.txt.yview); xs = ttk.Scrollbar(right, orient='horizontal', command=self.txt.xview)
        self.txt.config(yscrollcommand=ys.set, xscrollcommand=xs.set)
        xs.pack(side='bottom', fill='x'); self.txt.pack(side='left', fill='both', expand=True); ys.pack(side='right', fill='y')
        self.txt.tag_configure('head', font=('Consolas', 9, 'bold'), foreground='#1d4f91')
        self.txt.tag_configure('val', foreground='#7a3e00')
        self.txt.tag_configure('found', background='#fff27a')
        self.txt.tag_configure('found_cur', background='#ff9f40')
        self.txt.bind('<Control-f>', lambda e: self.find_open())
        self.txt.bind('<Double-1>', self.follow)
        self.welcome()

    def welcome(self):
        """Start text; shows the build bar while the reference data is missing."""
        if self.src.available(): self.buildbar.pack_forget()
        elif not self.buildbar.winfo_manager(): self.buildbar.pack(fill='x', before=self.pw, pady=(0, 4))
        if self.intro is not None:
            if self.src.available(): self.after(100, self.suggest)
            self.put(self.intro() if callable(self.intro) else self.intro)
        elif not self.src.available():
            self.put(NOT_BUILT)
        else:
            self.after(100, self.suggest)
            self.put('Pick something from the list on the left, or search (several words allowed, e.g. "door time").\n\n'
                     'Show: Events = every scripted event / cutscene trigger; Story steps = quest progress;\n'
                     'Flags = saved and runtime flags; Computed flags = conditions worked out from other flags.\n\n'
                     'Examples:\n  Step_DoorOfTime\n'
                     '  Market_Child_DoorOfTime_Draw      (pull the Master Sword)\n  HyruleCastle_Goto_HyruleCastle_MeetZelda\n'
                     '  Market_Adult_Field_GetLightPrelude\n  Step_Goto_HyruleCastle\n\nIn any flag tab: right-click a row, '
                     'or select it and press Ctrl+I.\n\nIn event flows "YES"/"NO" are the branches taken when the check is true/false.')

    def put(self, text):
        self.txt.config(state='normal'); self.txt.delete('1.0', 'end')
        cw = tkfont.Font(font=self.txt['font']).measure('0')
        for line in text.split('\n'):
            n = len(line) - len(line.lstrip(' '))
            ind = 'ind%d' % n
            self.txt.tag_configure(ind, lmargin2=(n + 4) * cw)
            self.txt.insert('end', line + '\n', ('head', ind) if line and not n else (ind,))
        self.txt.config(state='disabled')
        if self.findbar.winfo_ismapped(): self.find_all()

    def find_open(self):
        if not self.findbar.winfo_ismapped(): self.findbar.pack(fill='x', before=self.pw, pady=(0, 4))
        self.fentry.focus_set(); self.fentry.select_range(0, 'end')
        self.find_all()
        return 'break'

    def find_close(self):
        self.findbar.pack_forget()
        self.txt.tag_remove('found', '1.0', 'end'); self.txt.tag_remove('found_cur', '1.0', 'end')
        self.fmatches, self.fpos = [], -1
        return 'break'

    def find_all(self):
        """Highlight every case-insensitive match of the find text in the report."""
        self.txt.tag_remove('found', '1.0', 'end'); self.txt.tag_remove('found_cur', '1.0', 'end')
        self.fmatches, self.fpos = [], -1
        q = self.fq.get()
        if not q:
            self.fcount.config(text='')
            return
        start, n = '1.0', tk.IntVar()
        while True:
            idx = self.txt.search(q, start, stopindex='end', nocase=True, count=n)
            if not idx or not n.get(): break
            end = '%s+%dc' % (idx, n.get())
            self.txt.tag_add('found', idx, end)
            self.fmatches.append((idx, end))
            start = end
        if self.fmatches: self.find_step(1)
        else: self.fcount.config(text='no matches')

    def find_step(self, d):
        if not self.fmatches: return 'break'
        self.fpos = (self.fpos + d) % len(self.fmatches)
        a, b = self.fmatches[self.fpos]
        self.txt.tag_remove('found_cur', '1.0', 'end'); self.txt.tag_add('found_cur', a, b)
        self.txt.see(a)
        self.fcount.config(text='%d / %d' % (self.fpos + 1, len(self.fmatches)))
        return 'break'

    def suggest(self):
        q = self.q.get().strip()
        self.lb.delete(0, 'end')
        if not self.src.available(): return
        res = self.src.search(q, self.kind.get())
        for n in res: self.lb.insert('end', n)
        self.count.config(text='%d %s' % (len(res), self.kind.get().lower()))

    def show(self, q, keep_query=False, push=True):
        q = q.strip()
        if not q: return
        if push and (not self.history or self.history[-1] != q): self.history.append(q)
        if not keep_query: self.q.set(q)
        self.put('== %s\n\n%s' % (q, self.src.report(q, raw=self.raw.get())))

    def back(self):
        if len(self.history) > 1:
            self.history.pop(); self.show(self.history[-1], push=False)

    def follow(self, e):
        idx = self.txt.index('@%d,%d' % (e.x, e.y))
        line = self.txt.get(idx + ' linestart', idx + ' lineend')
        col = int(idx.split('.')[1])
        for m in re.finditer(r'[A-Za-z_][A-Za-z0-9_.]*', line):
            if m.start() <= col <= m.end():
                w = m.group(0).rstrip('.')
                self.show(w); return 'break'
        return 'break'

class ComparePane(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        top = ttk.Frame(self); top.pack(fill='x', pady=4)
        self.pa, self.pb = tk.StringVar(), tk.StringVar()
        for i, (lab, var) in enumerate((('A', self.pa), ('B', self.pb))):
            ttk.Label(top, text=lab).grid(row=i, column=0, padx=4, sticky='w')
            ttk.Entry(top, textvariable=var, width=110).grid(row=i, column=1, sticky='we')
            ttk.Button(top, text='Browse', command=lambda v=var: self.browse(v)).grid(row=i, column=2, padx=4)
        ttk.Button(top, text='Use loaded save as A', command=self.use_loaded).grid(row=0, column=3)
        ttk.Button(top, text='Compare', command=self.run).grid(row=1, column=3, sticky='we')
        top.columnconfigure(1, weight=1)
        bar = ttk.Frame(self); bar.pack(fill='x')
        ttk.Label(bar, text='Search').pack(side='left', padx=4)
        self.q = tk.StringVar(); ttk.Entry(bar, textvariable=self.q, width=40).pack(side='left')
        self.q.trace_add('write', lambda *a: self.show())
        self.hide_noise = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text='Hide position/time/stat noise', variable=self.hide_noise,
                        command=self.show).pack(side='left', padx=8)
        ttk.Button(bar, text='Copy B value into loaded save', command=self.copy_b).pack(side='right', padx=4)
        self.count = ttk.Label(bar, foreground='#666'); self.count.pack(side='right', padx=8)
        frame = ttk.Frame(self); frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(frame, columns=('type', 'a', 'b', 'info'), selectmode='extended')
        self.tree.heading('#0', text='Flag')
        for c, t, w in (('type', 'Type', 90), ('a', 'A', 200), ('b', 'B', 200), ('info', 'Info', 300)):
            self.tree.heading(c, text=t); self.tree.column(c, width=w, stretch=c == 'info')
        self.tree.column('#0', width=420)
        sb = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.rows = []

    def browse(self, var):
        p = filedialog.askopenfilename(initialdir=self.app.last_dir, filetypes=[('Saves', '*.sav'), ('All', '*.*')])
        if p: var.set(p); self.app.last_dir = os.path.dirname(p)

    def use_loaded(self):
        if self.app.save: self.pa.set(self.app.save.path + ('  (loaded, with unsaved edits)' if self.app.changed else ''))

    def run(self):
        try:
            a = self.app.save if self.pa.get().startswith(self.app.save.path if self.app.save else '\0') else Save(self.pa.get())
            b = Save(self.pb.get())
        except (OSError, ValueError) as e:
            messagebox.showerror('Compare', str(e)); return
        self.rows = list(diff(a, b))
        self.show()

    NOISE = re.compile(r'Pos|Dir|Time|Count|Total|Play|Frame|RadY|Date|Sequence_|Random|Counter|Num$', re.I)

    def show(self):
        self.tree.delete(*self.tree.get_children())
        q = self.q.get().lower(); n = 0
        for h, t, va, vb in self.rows:
            nm = name(h); info = ACTOR.get(h, '')
            if q and q not in nm.lower() and q not in info.lower(): continue
            if self.hide_noise.get() and (nm.startswith('?') and t not in ('Bool', 'Enum') or self.NOISE.search(nm) and t != 'Bool'):
                continue
            self.tree.insert('', 'end', iid=str(h), text=nm, values=(t, fmt(va)[:200], fmt(vb)[:200], info)); n += 1
        self.count.config(text='%d differences shown / %d total' % (n, len(self.rows)))

    def copy_b(self):
        s = self.app.save
        if not s: messagebox.showinfo('Copy', 'Load a save first.'); return
        done = skipped = 0
        for i in self.tree.selection():
            h = int(i)
            vb = next(r[3] for r in self.rows if r[0] == h)
            if h not in s.entries or s.type(h) not in EDITABLE or vb == '<absent>': skipped += 1; continue
            try: self.app.set(h, vb); done += 1
            except ValueError: skipped += 1
        self.app.refresh_all()
        messagebox.showinfo('Copy', 'Copied %d values into the loaded save (%d skipped). Save to write the file.' % (done, skipped))


SPAWNS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spawns.json')
MOD_CLIENT_DIR = os.path.expandvars(r'%USERPROFILE%\Documents\oot_tools_share\mod')
LAST_GROUND_POS = 0x8773f02d  # unnamed Vector3 that follows SavePos (last position on ground)
MAP_NAME_2 = 0x4a6bdb7d  # unnamed String32 that usually holds the same map name


class SpawnPane(ttk.Frame):
    """Picks the map and position Link loads at: Sequence_CurrentBanc, PlayerStatus.SavePos / SavePosRadY and the map
    marker. Spawn points are the StartPos actors of each map (spawns.json)."""

    FIELDS = ('Sequence_CurrentBanc', 'PlayerStatus.SavePos', 'PlayerStatus.SavePosRadY', 'Player_Pos_For_Map',
              'Player_Rot_For_Map')

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        try: self.spawns = json.load(open(SPAWNS_PATH, encoding='utf8'))
        except OSError: self.spawns = {}
        top = ttk.Frame(self); top.pack(fill='x', padx=6, pady=6)
        ttk.Label(top, text='Map:').pack(side='left')
        self.map = tk.StringVar()
        self.maps = ttk.Combobox(top, textvariable=self.map, values=sorted(self.spawns), width=36)
        self.maps.pack(side='left', padx=4)
        self.maps.bind('<<ComboboxSelected>>', lambda e: self.fill())
        self.maps.bind('<Return>', lambda e: self.fill())
        self.cur = ttk.Label(top, text='', foreground='#444'); self.cur.pack(side='left', padx=12)
        pw = ttk.PanedWindow(self, orient='horizontal'); pw.pack(fill='both', expand=True, padx=6)
        left = ttk.Frame(pw); pw.add(left, weight=2)
        self.tv = ttk.Treeview(left, columns=('name', 'pos', 'yaw', 'file'), show='headings', selectmode='browse')
        for c, w in (('name', 260), ('pos', 220), ('yaw', 70), ('file', 70)):
            self.tv.heading(c, text=c); self.tv.column(c, width=w, stretch=c == 'name')
        self.tv.pack(fill='both', expand=True)
        self.tv.bind('<<TreeviewSelect>>', lambda e: self.pick())
        right = ttk.Frame(pw); pw.add(right, weight=3)
        self.canvas = tk.Canvas(right, background='#1e1e1e', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda e: self.draw())
        self.canvas.bind('<Button-1>', self.click)
        form = ttk.Frame(self); form.pack(fill='x', padx=6, pady=6)
        self.xyz = [tk.StringVar() for _ in range(3)]
        self.yaw = tk.StringVar(value='0')
        for i, n in enumerate('XYZ'):
            ttk.Label(form, text=n).pack(side='left', padx=(8 if i else 0, 2))
            ttk.Entry(form, textvariable=self.xyz[i], width=10).pack(side='left')
        ttk.Label(form, text='facing (rad)').pack(side='left', padx=(8, 2))
        ttk.Entry(form, textvariable=self.yaw, width=8).pack(side='left')
        self.ground = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text='also set last ground position (8773f02d)', variable=self.ground).pack(side='left', padx=8)
        self.map2 = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text='also set 2nd map name (4a6bdb7d)', variable=self.map2).pack(side='left')
        ttk.Button(form, text="Use Link's position (mod)", command=self.from_game).pack(side='left', padx=4)
        ttk.Button(form, text='Apply to save', command=self.apply).pack(side='left', padx=4)
        self.hint = ttk.Label(self, foreground='#555', justify='left')
        self.hint.pack(fill='x', padx=6, pady=(0, 6))
        self.rows = []
        self.set_hint()

    def set_hint(self):
        self.hint.config(text=(
            'Pick a map and a spawn point (list or click the top-down plot), then Apply and Save. Sets the map Link loads in '
            '(Sequence_CurrentBanc), the position and facing he loads at (PlayerStatus.SavePos / SavePosRadY) and the pause-map '
            'marker.\nThe map name also decides the age (_Child / _Adult maps). Story flags are not changed: a map can still '
            'play its own events or send you elsewhere.' if self.spawns else
            'Spawn points not built: use "Build reference data…" in the toolbar.'))

    def reload(self):
        try: self.spawns = json.load(open(SPAWNS_PATH, encoding='utf8'))
        except (OSError, ValueError): self.spawns = {}
        self.maps.config(values=sorted(self.spawns))
        self.set_hint()
        self.load()

    def load(self):
        s = self.app.save
        if not s: return
        banc = self.get('Sequence_CurrentBanc') or ''
        pos = self.get('PlayerStatus.SavePos') or [0, 0, 0]
        self.cur.config(text='In save: %s at %s facing %s' % (banc or '?', pos, self.get('PlayerStatus.SavePosRadY')))
        if banc in self.spawns: self.map.set(banc)
        for v, x in zip(self.xyz, pos): v.set(str(x))
        self.yaw.set(str(self.get('PlayerStatus.SavePosRadY') or 0))
        self.fill()

    def refresh(self):
        self.load()

    def get(self, key):
        h = key if isinstance(key, int) else BY_NAME.get(key)
        return self.app.save.get(h) if h in self.app.save.entries else None

    def fill(self):
        self.tv.delete(*self.tv.get_children())
        self.rows = self.spawns.get(self.map.get(), [])
        for i, r in enumerate(self.rows):
            self.tv.insert('', 'end', iid=str(i), values=(r['name'], '%.2f, %.2f, %.2f' % tuple(r['pos']), r['yaw'], r['file']))
        self.draw()

    def pick(self, i=None):
        if i is None:
            sel = self.tv.selection()
            if not sel: return
            i = int(sel[0])
        r = self.rows[i]
        for v, x in zip(self.xyz, r['pos']): v.set(str(x))
        self.yaw.set(str(r['yaw']))
        self.draw()

    def bounds(self):
        xs = [r['pos'][0] for r in self.rows] or [0]; zs = [r['pos'][2] for r in self.rows] or [0]
        try: xs.append(float(self.xyz[0].get())); zs.append(float(self.xyz[2].get()))
        except ValueError: pass
        w, h = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
        span = max(max(xs) - min(xs), max(zs) - min(zs), 10) * 1.15
        cx, cz = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2
        k = min(w, h) / span
        return (lambda x, z: (w / 2 + (x - cx) * k, h / 2 + (z - cz) * k)), k

    def draw(self):
        c = self.canvas; c.delete('all')
        if not self.rows: return
        to, k = self.bounds()
        sel = self.tv.selection()
        for i, r in enumerate(self.rows):
            x, y = to(r['pos'][0], r['pos'][2])
            on = sel and int(sel[0]) == i
            col = '#ffd23f' if on else '#4fc3f7'
            c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=col, outline='')
            c.create_line(x, y, x + 12 * math.sin(r['yaw']), y + 12 * math.cos(r['yaw']), fill=col, width=2)
            c.create_text(x + 8, y - 8, text=r['name'], fill='#ddd' if on else '#999', anchor='sw', font=('Segoe UI', 8))
        try:
            x, y = to(float(self.xyz[0].get()), float(self.xyz[2].get()))
            c.create_line(x - 8, y - 8, x + 8, y + 8, fill='#ff5252', width=2); c.create_line(x - 8, y + 8, x + 8, y - 8, fill='#ff5252', width=2)
        except ValueError: pass
        c.create_text(6, 6, anchor='nw', fill='#777', text='top-down: x right, z down   red X = position to write',
                      font=('Segoe UI', 8))

    def click(self, e):
        if not self.rows: return
        to, _ = self.bounds()
        best = min(range(len(self.rows)), key=lambda i: (to(self.rows[i]['pos'][0], self.rows[i]['pos'][2])[0] - e.x) ** 2 +
                   (to(self.rows[i]['pos'][0], self.rows[i]['pos'][2])[1] - e.y) ** 2)
        self.tv.selection_set(str(best)); self.tv.see(str(best))

    def from_game(self):
        try:
            if MOD_CLIENT_DIR not in sys.path: sys.path.insert(0, MOD_CLIENT_DIR)
            from client import Game
            g = Game(timeout=3.0)
            li = g.link(); g.close()
        except Exception as ex:
            messagebox.showerror('Mod', 'Could not read Link from the oottools mod: %s' % ex); return
        if not li['valid']: messagebox.showerror('Mod', 'Link not found in game'); return
        for v, x in zip(self.xyz, li['pos']): v.set('%.3f' % x)
        self.draw()

    def apply(self):
        if not self.app.save: return
        m = self.map.get().strip()
        try:
            pos = [float(v.get()) for v in self.xyz]; yaw = float(self.yaw.get())
        except ValueError:
            messagebox.showerror('Spawn', 'X, Y, Z and facing must be numbers'); return
        if not m: messagebox.showerror('Spawn', 'Pick a map'); return
        if m not in self.spawns and not messagebox.askyesno('Spawn', '%s is not a known map name. Write it anyway?' % m): return
        deg = math.degrees(yaw) + 180
        deg = (deg + 180) % 360 - 180
        vals = {'Sequence_CurrentBanc': m, 'PlayerStatus.SavePos': pos, 'PlayerStatus.SavePosRadY': yaw,
                'Player_Pos_For_Map': pos, 'Player_Rot_For_Map': round(deg, 4)}
        if self.ground.get(): vals[LAST_GROUND_POS] = pos
        if self.map2.get(): vals[MAP_NAME_2] = m
        missing = []
        for k, v in vals.items():
            h = k if isinstance(k, int) else BY_NAME.get(k)
            if h not in self.app.save.entries: missing.append(str(k)); continue
            self.app.set(h, v)
        self.app.refresh_all()
        messagebox.showinfo('Spawn', 'Set %s at %s.%s\nClick Save to write the file.' % (
            m, pos, ('\nNot in this save: ' + ', '.join(missing)) if missing else ''))


class App(tk.Tk):
    def __init__(self, path=None):
        super().__init__()
        self.title('OoT Save Editor'); self.geometry('1300x800')
        try: ttk.Style().theme_use('vista')
        except tk.TclError: pass
        self.save = None; self.changed = set()
        self.last_dir = DEFAULT_DIR if os.path.isdir(DEFAULT_DIR) else os.getcwd()
        bar = ttk.Frame(self); bar.pack(fill='x', padx=6, pady=6)
        ttk.Button(bar, text='Open slot…', command=self.pick_slot).pack(side='left')
        ttk.Button(bar, text='Open file…', command=self.open).pack(side='left', padx=(4, 0))
        ttk.Button(bar, text='Save', command=self.write).pack(side='left', padx=4)
        ttk.Button(bar, text='Save as…', command=self.write_as).pack(side='left')
        ttk.Button(bar, text='Revert', command=self.revert).pack(side='left', padx=4)
        ttk.Button(bar, text='About', command=self.about).pack(side='right')
        ttk.Button(bar, text='Build reference data…', command=self.build_data).pack(side='right', padx=4)
        self.status = ttk.Label(bar, text='No save loaded', foreground='#444'); self.status.pack(side='left', padx=12)
        self.nb = ttk.Notebook(self); self.nb.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        self.tables = []
        self.overview = Overview(self.nb, self); self.nb.add(self.overview, text='Overview')
        self.tables.append(self.overview)
        for title, rx, strip in CATEGORIES:
            t = FlagTable(self.nb, self, rx, strip); self.nb.add(t, text=title); self.tables.append(t)
            if title == 'Chests':
                for tt, pre in (('Gold Skulltulas', 'Skulltula_Gold'), ('Actor flags', '')):
                    a = ActorKeyTable(self.nb, self, pre); self.nb.add(a, text=tt); self.tables.append(a)
        self.spawn = SpawnPane(self.nb, self); self.nb.add(self.spawn, text='Spawn point'); self.tables.append(self.spawn)
        self.compare = ComparePane(self.nb, self); self.nb.add(self.compare, text='Compare')
        self.explorer = Explorer(self.nb, self); self.nb.add(self.explorer, text='Triggers & events')
        self.stats = Explorer(self.nb, self, src=ootstats, kind='Enemies', raw_text='All parameters', intro=stats_intro)
        self.nb.add(self.stats, text='Enemies & Link stats')
        self.drops = Explorer(self.nb, self, src=ootdrops, kind='Items', raw_text='Raw data', intro=drops_intro)
        self.nb.add(self.drops, text='Drops')
        self.protocol('WM_DELETE_WINDOW', self.quit_app)
        self.bind('<Control-s>', lambda e: self.write()); self.bind('<Control-o>', lambda e: self.open())
        self.bind('<Control-f>', self.find)
        if path: self.load(path)
        elif os.path.isdir(DEFAULT_DIR): self.after(200, self.pick_slot)

    def about(self):
        info = data_info()
        win = tk.Toplevel(self); win.title('About'); win.resizable(False, False); win.transient(self)
        f = ttk.Frame(win, padding=16); f.pack()
        ttk.Label(f, text=APP_NAME, font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        ttk.Label(f, text='Version %s' % APP_VERSION).pack(anchor='w')
        ttk.Label(f, text='By %s' % APP_AUTHOR).pack(anchor='w', pady=(8, 0))
        link = ttk.Label(f, text=APP_URL, foreground='#1d4f91', cursor='hand2')
        link.pack(anchor='w'); link.bind('<Button-1>', lambda e: webbrowser.open(APP_URL))
        if info:
            game = 'Game version (reference data): %s' % info.get('game_version', 'unknown')
            if info.get('main_build_id'): game += '\nmain build id: %s' % info['main_build_id']
            game += '\nBuilt: %s' % info.get('built', '?')
        else:
            game = 'Reference data not built'
        ttk.Label(f, text=game, justify='left').pack(anchor='w', pady=(8, 0))
        if self.save:
            ttk.Label(f, text='Save game data revision: %d' % self.save.version).pack(anchor='w')
        ttk.Button(f, text='Close', command=win.destroy).pack(anchor='e', pady=(12, 0))

    def build_data(self):
        """Runs tools/build_all.py on a romfs folder with live output, then reloads the reference data."""
        romfs = filedialog.askdirectory(title='Select the romfs folder of the game dump', mustexist=True)
        if not romfs: return
        if not os.path.isdir(os.path.join(romfs, 'Pack')):
            messagebox.showerror('Build reference data', 'Not a romfs folder (no Pack folder in it):\n%s' % romfs)
            return
        win = tk.Toplevel(self); win.title('Building reference data'); win.geometry('640x360'); win.transient(self)
        out = tk.Text(win, font=('Consolas', 9)); out.pack(fill='both', expand=True)
        close = ttk.Button(win, text='Close', command=win.destroy, state='disabled'); close.pack(anchor='e', padx=6, pady=6)
        q = queue.Queue()

        def run():
            p = subprocess.Popen([sys.executable, '-u', os.path.join(HERE, 'tools', 'build_all.py'), romfs],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf8', errors='replace',
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for line in p.stdout: q.put(line)
            q.put(None if p.wait() == 0 else 'FAILED')

        def pump():
            while not q.empty():
                line = q.get()
                if line is None or line == 'FAILED':
                    out.insert('end', '\nDone.\n' if line is None else '\nBuild failed.\n'); out.see('end')
                    close.config(state='normal')
                    if line is None: self.reload_data()
                    return
                out.insert('end', line); out.see('end')
            win.after(100, pump)

        threading.Thread(target=run, daemon=True).start()
        pump()

    def reload_data(self):
        ootrefs._cache.clear()
        ootstats._cache.clear()
        ootstats._CATCH = None
        ootdrops._cache.clear()
        self.explorer.welcome()
        self.stats.welcome()
        self.drops.welcome()
        self.spawn.reload()

    def find(self, e=None):
        """Ctrl+F: the find bar of a report tab (Triggers & events, stats), else the first text box of the tab."""
        tab = self.nametowidget(self.nb.select())
        if hasattr(tab, 'find_open'): return tab.find_open()
        stack = list(tab.winfo_children())
        while stack:
            w = stack.pop(0)
            if isinstance(w, ttk.Entry):
                w.focus_set(); w.select_range(0, 'end')
                return 'break'
            stack.extend(w.winfo_children())
        return 'break'

    def explore(self, q):
        self.nb.select(self.explorer); self.explorer.show(q)

    def pick_slot(self):
        if not self.confirm_discard(): return
        p = SlotPicker(self, self.last_dir if self.save else DEFAULT_DIR).result
        if p: self.load(p)

    def confirm_discard(self):
        return not self.changed or messagebox.askyesno('Unsaved changes', 'Discard %d unsaved changes?' % len(self.changed))

    def open(self):
        if not self.confirm_discard(): return
        p = filedialog.askopenfilename(initialdir=self.last_dir, filetypes=[('Saves', '*.sav'), ('All', '*.*')])
        if p: self.load(p)

    def load(self, path):
        try: self.save = Save(path)
        except (OSError, ValueError) as e: messagebox.showerror('Open', str(e)); return
        self.last_dir = os.path.dirname(path); self.changed = set()
        for t in self.tables: t.load()
        self.compare.pa.set(path)
        self.update_status()

    def update_status(self):
        s = self.save
        named = sum(1 for h in s.entries if not name(h).startswith('?'))
        self.status.config(text='%s   |   %d flags, %d named   |   %d unsaved change(s)' %
                           (s.path, len(s.entries), named, len(self.changed)))

    def mark(self, h):
        self.changed.add(h); self.update_status()

    def set(self, h, v):
        self.save.set(h, v); self.mark(h)

    def refresh_all(self):
        for t in self.tables: t.refresh()
        self.update_status()

    def write(self):
        if not self.save: return
        self.save.write()
        self.changed = set(); self.refresh_all()
        messagebox.showinfo('Saved', 'Written %s\nThe first original is kept as .bak next to it.\n'
                            'Close the game/emulator (or load from title) before using the edited save.' % self.save.path)

    def write_as(self):
        if not self.save: return
        p = filedialog.asksaveasfilename(initialdir=self.last_dir, initialfile=os.path.basename(self.save.path))
        if p:
            self.save.write(p); self.changed = set(); self.refresh_all()

    def revert(self):
        if self.save and self.confirm_discard(): self.changed = set(); self.load(self.save.path)

    def quit_app(self):
        if self.confirm_discard(): self.destroy()


if __name__ == '__main__':
    App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
