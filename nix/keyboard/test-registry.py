#!/usr/bin/env python3
"""Resolve GNOME's registered layout and compare all 416 captured keysyms."""
import ctypes as C
import os
from pathlib import Path
import re
import sys

library, include, reference = map(Path, sys.argv[1:])
os.environ['XKB_CONFIG_ROOT'] = str(include)
registry = C.CDLL(str(library/'libxkbregistry.so'))
xkb = C.CDLL(str(library/'libxkbcommon.so'))


def bind(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, args
    return fn


ptr, string, uint = C.c_void_p, C.c_char_p, C.c_uint32
context = bind(registry, 'rxkb_context_new', ptr, C.c_int)(0)
assert context and bind(registry, 'rxkb_context_parse', C.c_bool, ptr, string)(context, b'evdev')
layout = bind(registry, 'rxkb_layout_first', ptr, ptr)(context)
next_layout = bind(registry, 'rxkb_layout_next', ptr, ptr)
name = bind(registry, 'rxkb_layout_get_name', string, ptr)
variant = bind(registry, 'rxkb_layout_get_variant', string, ptr)
found = []
while layout:
    if name(layout) == b'gemini':
        found.append(variant(layout))
    layout = next_layout(layout)
assert found.count(None) == found.count(b'us') == 1, found
bind(registry, 'rxkb_context_unref', None, ptr)(context)


class Names(C.Structure):
    _fields_ = [(key, string) for key in ('rules', 'model', 'layout', 'variant', 'options')]


context = bind(xkb, 'xkb_context_new', ptr, C.c_int)(0)
names = Names(b'evdev', b'pc105', b'gemini', b'us', b'')
keymap = bind(xkb, 'xkb_keymap_new_from_names', ptr, ptr, C.POINTER(Names), C.c_int)(context, C.byref(names), 0)
assert keymap
state = bind(xkb, 'xkb_state_new', ptr, ptr)(keymap)
assert state
index = bind(xkb, 'xkb_keymap_mod_get_index', uint, ptr, string)
mods = [index(keymap, mod) for mod in (b'Shift', b'Mod5', b'Lock')]
assert all(mod < 32 for mod in mods)
update = bind(xkb, 'xkb_state_update_mask', uint, ptr, uint, uint, uint, uint, uint, uint)
symbol = bind(xkb, 'xkb_state_key_get_one_sym', uint, ptr, uint)
rows = re.findall(r'\{ (\d+), \{ ([0-9a-fx, ]+) \} \}', reference.read_text())
assert len(rows) == 52
for code, expected in rows:
    expected = [int(value.strip(), 16) for value in expected.split(',')]
    assert len(expected) == 8
    for level, value in enumerate(expected):
        update(state, ((1 << mods[0]) if level & 1 else 0) | ((1 << mods[1]) if level & 2 else 0),
               0, (1 << mods[2]) if level & 4 else 0, 0, 0, 0)
        actual = symbol(state, int(code)+8)
        assert actual == value, (code, level, hex(actual), hex(value))
bind(xkb, 'xkb_state_unref', None, ptr)(state)
bind(xkb, 'xkb_keymap_unref', None, ptr)(keymap)
bind(xkb, 'xkb_context_unref', None, ptr)(context)
print('GNOME registry: gemini+us; captured key combinations: 416 passed')
