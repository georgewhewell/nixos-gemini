#!/usr/bin/env python3
"""Resolve the original Gemian map into a reviewable desktop keysym fixture."""
import argparse
import ctypes as C
import hashlib
from pathlib import Path
import re
import tempfile

HERE = Path(__file__).resolve().parent
SYMBOL_SHA = '56baafdde43da9e3d66474f231a9bfd9d8d9fda40cd4c4af939ae1251db426cb'
CODES_SHA = 'fc712134de609b50e0600c251d52a0fd2e3ffd5002215f8513f663c177773e3e'
# Same 52 Linux keycodes as the hardware-qualified AW9523 DT matrix.
CODES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 19,
         20, 21, 22, 23, 24, 25, 28, 29, 30, 31, 32, 33, 34, 35, 36,
         37, 38, 40, 42, 44, 45, 46, 47, 48, 49, 50, 51, 52, 54, 56,
         57, 103, 105, 106, 108, 125]


def generate(library, include):
    x = C.CDLL(str(library))
    def bind(name, result, *args):
        fn = getattr(x, 'xkb_' + name)
        fn.restype, fn.argtypes = result, args
        return fn
    ptr, uint, string = C.c_void_p, C.c_uint32, C.c_char_p
    context_new = bind('context_new', ptr, C.c_int)
    append = bind('context_include_path_append', C.c_int, ptr, string)
    keymap_new = bind('keymap_new_from_string', ptr, ptr, string, C.c_int, C.c_int)
    state_new = bind('state_new', ptr, ptr)
    mod_index = bind('keymap_mod_get_index', uint, ptr, string)
    update = bind('state_update_mask', uint, ptr, uint, uint, uint, uint, uint, uint)
    symbol = bind('state_key_get_one_sym', uint, ptr, uint)
    with tempfile.TemporaryDirectory(prefix='gemini-reference-') as tmp:
        tmp = Path(tmp)
        for source, target, sha in (
                ('gemini-symbols', 'symbols/planet_vndr/gemini', SYMBOL_SHA),
                ('reference-evdev', 'keycodes/evdev', CODES_SHA)):
            raw = (HERE / source).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == sha
            path = tmp / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        context = context_new(1)
        assert context and append(context, str(tmp).encode()) and append(context, str(include).encode())
        keymap = keymap_new(context, b'''xkb_keymap {
          xkb_keycodes { include "evdev" };
          xkb_types { include "complete" };
          xkb_compatibility { include "complete" };
          xkb_symbols { include "pc+planet_vndr/gemini(us)" };
        };''', 1, 0)
        assert keymap
        state = state_new(keymap)
        assert state
        mods = [mod_index(keymap, name) for name in (b'Shift', b'Mod5', b'Lock')]
        assert all(m < 32 for m in mods)
        out = ['/* Generated from captured Gemian symbols/keycodes; see generate-reference.py. */',
               '/* Columns: plain, Shift, Fn, Fn+Shift, then the same with Caps. */',
               'static const struct { unsigned int code; xkb_keysym_t sym[8]; } reference[] = {']
        for code in CODES:
            values = []
            for level in range(8):
                update(state, ((1 << mods[0]) if level & 1 else 0) |
                       ((1 << mods[1]) if level & 2 else 0), 0,
                       (1 << mods[2]) if level & 4 else 0, 0, 0, 0)
                values.append(symbol(state, code + 8))
            out.append('    { %d, { %s } },' % (code, ', '.join(hex(v) for v in values)))
        out += ['};', '']
        bind('state_unref', None, ptr)(state)
        bind('keymap_unref', None, ptr)(keymap)
        bind('context_unref', None, ptr)(context)
    return '\n'.join(out)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--library', type=Path, required=True)
    p.add_argument('--include', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--matrix', type=Path, required=True)
    p.add_argument('--input-header', type=Path, required=True)
    a = p.parse_args()
    numbers = {name: int(number) for name, number in re.findall(
        r'^#define\s+(KEY_\w+)\s+(\d+)\s*$', a.input_header.read_text(), re.M)}
    names = re.findall(r'MATRIX_KEY\(\d+, \d+, (KEY_\w+)\)', a.matrix.read_text())
    assert len(names) == len(set(names)) == 52
    assert sorted(numbers[name] for name in names) == CODES
    a.output.write_text(generate(a.library, a.include))
