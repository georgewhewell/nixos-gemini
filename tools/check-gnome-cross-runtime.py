#!/usr/bin/env python3
"""Check desktop, networking and telephony executables and runtime libraries."""
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
            if word == '--prefix' and words[index+1] in (
                    'GI_TYPELIB_PATH', 'QT_PLUGIN_PATH', 'QML_IMPORT_PATH', 'QML2_IMPORT_PATH',
                    'NIXPKGS_QT6_QML_IMPORT_PATH'):
                name = words[index+1]
                value = words[index+3]
                if value.encode()+b'\0' not in code:
                    raise ValueError(name+' missing from compiled wrapper: '+str(path))
                if name == 'GI_TYPELIB_PATH':
                    self.typelibs(value)
                else:
                    for directory in value.split(':'):
                        if not Path(directory).is_dir():
                            raise ValueError('Missing Qt runtime directory: '+directory)
                        self.tree(directory)

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


def esim_runtime(check, gui, lpac):
    check.tree(gui/'bin', executables=True)
    check.tree(lpac/'bin', executables=True)
    check.tree(lpac/'lib')
    for driver in ('driver_apdu_at.so', 'driver_apdu_at_csim.so'):
        check.file(lpac/'lib/lpac/driver'/driver)
    resource = gui/'share/lpa-gtk/lpa-gtk.gresource'
    if not resource.is_file() or resource.stat().st_size == 0:
        raise ValueError('Missing eSIM GUI resources')
    check.file(resource)
    modules = list((gui/'lib').glob('python*/site-packages/lpa_gtk/modemmanager.py'))
    if len(modules) != 1:
        raise ValueError('Missing or ambiguous eSIM ModemManager backend')
    check.file(modules[0])
    # The interpreter is an environment of symlinks. Its original prefix,
    # rather than the resolved Python binary, owns the GI/Cairo extensions.
    launcher = gui/'bin/.lpa-gtk-wrapped'
    shebang = launcher.read_text().splitlines()[0]
    if not shebang.startswith('#!/nix/store/'):
        raise ValueError('Invalid eSIM GUI interpreter')
    interpreter = Path(shebang[2:])
    check.file(interpreter, executable=True)
    sites = list((interpreter.parent.parent/'lib').glob('python*/site-packages'))
    if len(sites) != 1:
        raise ValueError('Missing or ambiguous eSIM Python environment')
    extensions = []
    for module, pattern in (('gi', '_gi.*.so'), ('gi', '_gi_cairo.*.so'),
                            ('cairo', '_cairo.*.so')):
        matches = list((sites[0]/module).glob(pattern))
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous eSIM Python extension: '+pattern)
        check.file(matches[0])
        extensions.append(str(matches[0].resolve()))
    environment = wrapper_environment(gui/'bin/lpa-gtk')
    check.typelibs(environment['GI_TYPELIB_PATH'])
    loaders = re.findall(r'^"([^"\n]+\.so)"',
                         Path(environment['GDK_PIXBUF_MODULE_FILE']).read_text(), flags=re.M)
    if not loaders:
        raise ValueError('No eSIM GUI pixbuf loaders')
    for loader in loaders:
        check.file(loader)
    return dict(gui=str(gui), lpac=str(lpac), python=str(interpreter),
                python_extensions=extensions, environment=environment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--system', type=Path, required=True)
    parser.add_argument('--shell', type=Path, required=True)
    parser.add_argument('--orca', type=Path, required=True)
    parser.add_argument('--networkmanager', type=Path, required=True)
    parser.add_argument('--modemmanager', type=Path, required=True)
    parser.add_argument('--calls', type=Path, required=True)
    parser.add_argument('--spacebar', type=Path, required=True)
    parser.add_argument('--callaudiod', type=Path, required=True)
    parser.add_argument('--lpa-gtk', type=Path, required=True)
    parser.add_argument('--lpac', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    for package in (args.system, args.shell, args.orca, args.networkmanager, args.modemmanager,
                    args.calls, args.spacebar, args.callaudiod, args.lpa_gtk, args.lpac):
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
    for package in (args.networkmanager, args.modemmanager, args.calls, args.spacebar,
                    args.callaudiod):
        for sub in ('bin', 'sbin', 'libexec'):
            check.tree(package/sub, executables=True)
        check.tree(package/'lib')
    check.file(args.calls/'lib/calls/plugins/provider/mm/libmm.so')
    check.file(args.calls/'share/systemd/user/calls-daemon.service')
    check.file(args.spacebar/'libexec/spacebar-daemon', executable=True)
    check.file(args.spacebar/'etc/xdg/autostart/org.kde.spacebar.daemon.desktop')
    check.file(args.callaudiod/'share/dbus-1/services/org.mobian_project.CallAudio.service')
    environment = wrapper_environment(args.orca/'bin/orca')
    check.typelibs(environment['GI_TYPELIB_PATH'])
    cache = Path(environment['GDK_PIXBUF_MODULE_FILE'])
    loaders = re.findall(r'^"([^"\n]+\.so)"', cache.read_text(), flags=re.M)
    if not loaders:
        raise ValueError('No loaders in the installed pixbuf cache')
    for loader in loaders:
        check.file(loader)
    esim = esim_runtime(check, args.lpa_gtk, args.lpac)
    result = dict(passed=not check.errors, elf_files=check.elf, script_files=check.scripts,
                  system=str(args.system), shell=str(args.shell), orca=str(args.orca),
                  networkmanager=str(args.networkmanager), modemmanager=str(args.modemmanager),
                  calls=str(args.calls), spacebar=str(args.spacebar), callaudiod=str(args.callaudiod),
                  orca_environment=environment, pixbuf_loaders=loaders, errors=check.errors,
                  esim=esim, hardware_tested=False)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(f"{'PASS' if result['passed'] else 'FAIL'}: {check.elf} ELF files and "
          f'{check.scripts} script interpreter checks; {len(check.errors)} foreign ELF files')
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
