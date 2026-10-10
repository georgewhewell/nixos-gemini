#!/usr/bin/env python3
"""Check installed desktop executables and Orca's actual runtime library paths."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex


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
            if executable and path.stat().st_size < 1024 * 1024:
                self.wrapper(path)
        elif executable and header.startswith(b'#!'):
            self.scripts += 1
            interpreter = header.splitlines()[0][2:].decode().strip().split()[0]
            if interpreter.startswith('/nix/store/'):
                self.file(interpreter, executable=True)
            for reference in re.findall(r'/nix/store/[0-9a-z]{32}-[\w.+-]+/[\w./+-]+',
                                        path.read_text(errors='replace')):
                target = Path(reference)
                if target.is_file() and os.access(target, os.X_OK):
                    self.file(target, executable=True)

    def wrapper(self, path):
        raw = path.read_bytes()
        marker = raw.find(b'# The C-code for this binary wrapper')
        if marker < 0:
            return
        code = raw[:marker]
        description = raw[marker:].split(b'\0', 1)[0].decode(errors='replace')
        recipe = description.split('makeCWrapper ', 1)[1].split('\n\n# (Use ', 1)[0]
        words = shlex.split(recipe.replace('\\\n', ' '))
        self.file(words[0], executable=True)
        for index, word in enumerate(words):
            if word == '--prefix' and words[index+1] == 'GI_TYPELIB_PATH':
                value = words[index+3]
                if value.encode()+b'\0' not in code:
                    raise ValueError('Typelib path missing from compiled wrapper: '+str(path))
                self.typelibs(value)

    def typelibs(self, value):
        for directory in value.split(':'):
            path = Path(directory)
            if not path.is_dir() or path.parts[-2:] != ('lib', 'girepository-1.0'):
                raise ValueError('Invalid runtime typelib directory: '+directory)
            self.tree(path.parent)

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
    service_directory = args.system/'etc/systemd/system'
    if not service_directory.is_dir():
        raise ValueError('System service directory is missing')
    for service in service_directory.glob('*.service'):
        if not service.is_file():
            continue
        for command in re.findall(r'^Exec\w+=([^\n]+)', service.read_text(), flags=re.M):
            match = re.search(r'/nix/store/[0-9a-z]{32}-[\w.+-]+/[\w./+-]+', command)
            if match:
                check.file(match.group(), executable=True)
    for package in (args.shell, args.orca):
        for sub in ('bin', 'libexec', 'share/gnome-shell'):
            check.tree(package/sub, executables=True)
        check.tree(package/'lib')
    environment = wrapper_environment(args.orca/'bin/orca')
    check.typelibs(environment['GI_TYPELIB_PATH'])
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
