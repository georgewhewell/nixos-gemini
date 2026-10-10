#!/usr/bin/env python3
"""Check installed desktop executables and Orca's actual runtime library paths."""
import argparse
import json
import os
from pathlib import Path
import re


class Check:
    def __init__(self):
        self.seen = set()
        self.elf = 0
        self.scripts = 0
        self.errors = []

    def file(self, path, executable=False):
        path = Path(path).resolve()
        if path in self.seen:
            return
        if not path.is_file():
            self.errors.append(dict(path=str(path), problem='missing runtime file'))
            return
        self.seen.add(path)
        with path.open('rb') as stream:
            header = stream.read(512)
        if header[:4] == b'\x7fELF':
            self.elf += 1
            endian = 'little' if header[5] == 1 else 'big'
            machine = int.from_bytes(header[18:20], endian)
            if machine != 183:
                self.errors.append(dict(path=str(path), problem='foreign ELF', machine=machine))
        elif executable and header.startswith(b'#!'):
            self.scripts += 1
            interpreter = header.splitlines()[0][2:].decode().strip().split()[0]
            if interpreter.startswith('/nix/store/'):
                self.file(interpreter, executable=True)

    def tree(self, path, executables=False):
        for here, _, files in os.walk(path, followlinks=False):
            for name in files:
                file = Path(here)/name
                if not executables or os.access(file, os.X_OK):
                    self.file(file, executable=executables)


def wrapper_environment(path):
    raw = path.read_bytes()
    marker = raw.index(b'# The C-code for this binary wrapper')
    code, description = raw[:marker], raw[marker:].decode(errors='replace')
    environment = {}
    patterns = (
        r"--set 'GDK_PIXBUF_MODULE_FILE' '([^']+)'",
        r"--prefix 'GI_TYPELIB_PATH' ':' '([^']+)'",
    )
    for name, pattern in zip(('GDK_PIXBUF_MODULE_FILE', 'GI_TYPELIB_PATH'), patterns):
        values = re.findall(pattern, description)
        if len(values) != 1 or values[0].encode()+b'\0' not in code:
            raise ValueError('Missing or ambiguous compiled wrapper value: '+name)
        environment[name] = values[0]
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--system', type=Path, required=True)
    parser.add_argument('--shell', type=Path, required=True)
    parser.add_argument('--orca', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    for package in (args.system, args.shell, args.orca):
        if not package.is_dir():
            raise ValueError('Runtime package is missing: '+str(package))
    check = Check()
    check.tree(args.system/'sw/bin', executables=True)
    for package in (args.shell, args.orca):
        for sub in ('bin', 'libexec', 'share/gnome-shell'):
            check.tree(package/sub, executables=True)
        check.tree(package/'lib')
    environment = wrapper_environment(args.orca/'bin/orca')
    for directory in environment['GI_TYPELIB_PATH'].split(':'):
        path = Path(directory)
        if not path.is_dir() or path.parts[-2:] != ('lib', 'girepository-1.0'):
            raise ValueError('Invalid runtime typelib directory: '+directory)
        # Typelibs describe the libraries next to them. Check those libraries,
        # including symlinks, rather than relying on the package's name.
        check.tree(path.parent)
    cache = Path(environment['GDK_PIXBUF_MODULE_FILE'])
    loaders = re.findall(r'^"([^"\n]+\.so)"', cache.read_text(), flags=re.M)
    if not loaders:
        raise ValueError('No loaders in the installed pixbuf cache')
    for loader in loaders:
        check.file(loader)
    result = dict(passed=not check.errors, elf_files=check.elf, script_files=check.scripts,
                  system=str(args.system), shell=str(args.shell), orca=str(args.orca),
                  orca_environment=environment, pixbuf_loaders=loaders, errors=check.errors,
                  hardware_tested=False)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f"{'PASS' if result['passed'] else 'FAIL'}: {check.elf} ELF files and "
          f'{check.scripts} script interpreter checks; {len(check.errors)} foreign ELF files')
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
