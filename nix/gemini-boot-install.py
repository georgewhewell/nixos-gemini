#!/usr/bin/env python3
"""Install a built Gemini EFI generation while preserving older entries."""
import argparse
from contextlib import contextmanager
import fcntl
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile

PUBLISH = Path(os.environ.get('GEMINI_EFI_PUBLISH', Path(__file__).with_name('gemini-efi-publish.sh')))
MANAGER = 'EFI/systemd/systemd-bootaa64.efi'
CONFIG = 'loader/loader.conf'
SYSTEM_PATH = r'/nix/store/[0-9a-z]{32}-[A-Za-z0-9.+_-]+'
GENERATION_ROOTS = Path('/nix/var/nix/gcroots/gemini-boot')
SYSTEM_PROFILES = Path('/nix/var/nix/profiles')


def file_info(path):
    return dict(size=path.stat().st_size, sha256=digest(path))


def prepare_generation(system, staging, manager):
    """Prepare a standard NixOS toplevel, independent of installation images."""
    if not re.fullmatch(SYSTEM_PATH, str(system)) or not (system/'init').is_file():
        raise ValueError('Expected a NixOS system in /nix/store')
    sources = {'linux.efi': system/'kernel', 'initrd.cpio.gz': system/'initrd',
               'gemini.dtb': system/'gemini.dtb'}
    params = (system/'kernel-params').read_text().split()
    if any(p.startswith(('init=', 'rdinit=')) for p in params if p != 'rdinit=/init'):
        raise ValueError('System kernel parameters override NixOS init')
    options = ' '.join(params + ['init='+str(system)+'/init'])
    identity = hashlib.sha256(b'gemini-nixos-generation-v1\0'+options.encode())
    for path in sources.values():
        identity.update(bytes.fromhex(digest(path)))
    payload = identity.hexdigest()
    entry = 'gemini-'+payload+'.conf'
    directory = 'EFI/Gemini/'+payload
    paths = [MANAGER, *(directory+'/'+name for name in sources), 'loader/entries/'+entry, CONFIG]
    for name in paths:
        (staging/name).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manager, staging/MANAGER)
    for name, source in sources.items():
        shutil.copyfile(source, staging/directory/name)
    for name in (MANAGER, directory+'/linux.efi'):
        with (staging/name).open('rb') as stream:
            header = stream.read(64)
            if len(header) != 64 or header[:2] != b'MZ':
                raise ValueError('Boot image is not PE: '+name)
            stream.seek(struct.unpack_from('<I', header, 0x3c)[0])
            pe = stream.read(94)
        if (len(pe) != 94 or pe[:4] != b'PE\0\0' or
                struct.unpack_from('<H', pe, 4)[0] != 0xaa64 or
                struct.unpack_from('<H', pe, 24)[0] != 0x20b or
                struct.unpack_from('<H', pe, 92)[0] != 10):
            raise ValueError('Boot image is not an AArch64 EFI application: '+name)
    subprocess.run(['fdtput', '-t', 's', str(staging/directory/'gemini.dtb'),
                    '/chosen', 'gemini,efi-entry-id', payload], check=True)
    (staging/paths[-2]).write_text(
        'title NixOS Gemini\nsort-key gemini\nversion '+system.name[:32]+'\n'
        'linux /'+directory+'/linux.efi\ninitrd /'+directory+'/initrd.cpio.gz\n'
        'devicetree /'+directory+'/gemini.dtb\noptions '+options+'\n')
    (staging/CONFIG).write_text('default '+entry+'\ntimeout 8\nconsole-mode keep\n'
                              'editor no\nauto-entries no\nauto-firmware no\nrandom-seed-mode off\n')
    files = {name: file_info(staging/name) for name in paths}
    (staging/'files.manifest').write_text(''.join(
        f"{info['sha256']} {info['size']} {name}\n" for name, info in files.items()))
    return dict(payload_identity=payload, entry=entry, files=files,
                store=dict(system=str(system), root='/persist/nixos'),
                entry_device_tree=directory+'/gemini.dtb', menu_timeout_seconds=8)


def digest(path):
    with path.open('rb') as stream:
        sha = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular file: ' + str(path))
    return path


def checked_path(root, relative):
    path = root
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Boot path is a symlink: ' + str(path))
    return path


def matches(path, info):
    return not path.is_symlink() and path.is_file() and path.stat().st_size == info['size'] and digest(path) == info['sha256']


def prepare(package, staging):
    manifest = json.loads(regular(package/'manifest.json').read_text())
    identity = manifest['payload_identity']
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('Invalid EFI payload identity')
    entry = 'gemini-' + identity + '.conf'
    directory = 'EFI/Gemini/' + identity
    names = [MANAGER, directory+'/linux.efi', directory+'/initrd.cpio.gz',
             directory+'/gemini.dtb', 'loader/entries/'+entry, CONFIG]
    files = manifest['files']
    if manifest['entry'] != entry or set(files) != set(names):
        raise ValueError('EFI generation has unexpected files')
    store = manifest['store']
    persistent = store.get('root') == '/persist/nixos'
    for info in [*files.values(), manifest['archive']] + ([] if persistent else [store]):
        if (type(info['size']) is not int or info['size'] <= 0 or
                not re.fullmatch('[0-9a-f]{64}', info['sha256'])):
            raise ValueError('Invalid file size or digest')
    if (not re.fullmatch(SYSTEM_PATH, store['system']) or
            (not persistent and store['file'] != 'mainline-nixos-'+store['sha256']+'.squashfs')):
        raise ValueError('Invalid store image identity')
    archive = regular(package/'boot-files.tar')
    if manifest['archive']['size'] > 64 * 1024 * 1024 or not matches(archive, manifest['archive']):
        raise ValueError('EFI archive content differs from its manifest')
    with tarfile.open(archive, mode='r:') as source:
        members = source.getmembers()
        if len(members) != len(names) or {m.name for m in members} != set(names):
            raise ValueError('EFI archive members differ from the generation')
        for member in members:
            if not member.isfile() or member.size != files[member.name]['size']:
                raise ValueError('EFI archive contains an unexpected file type or size')
            target = staging/member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst)
            if not matches(target, files[member.name]):
                raise ValueError('EFI archive member content differs: '+member.name)
    entry_text = (staging/names[-2]).read_text().splitlines()
    if persistent:
        options = [line.removeprefix('options ').split() for line in entry_text if line.startswith('options ')]
        if len(options) != 1 or [p for p in options[0] if p.startswith('init=')] != ['init='+store['system']+'/init']:
            raise ValueError('Boot entry does not select its NixOS system')
    for kind, suffix in [('linux', 'linux.efi'), ('initrd', 'initrd.cpio.gz'), ('devicetree', 'gemini.dtb')]:
        if [line for line in entry_text if line.startswith(kind+' ')] != [kind+' /'+directory+'/'+suffix]:
            raise ValueError('Boot entry does not select its own payload')
    if [line for line in (staging/CONFIG).read_text().splitlines() if line.startswith('default ')] != ['default '+entry]:
        raise ValueError('Loader default does not select the generation')
    records = ''.join(f"{files[n]['sha256']} {files[n]['size']} {n}\n" for n in names)
    if regular(package/'files.manifest').read_text() != records:
        raise ValueError('Publication order or file manifest differs')
    (staging/'files.manifest').write_text(records)
    return manifest


class BootVolume:
    def __init__(self, path):
        self.path = path

    def require(self, writable=False):
        def unescape(value):
            return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)
        rows = [row.split() for row in Path('/proc/mounts').read_text().splitlines()]
        rows = [row for row in rows if unescape(row[1]) == str(self.path)]
        if self.path.is_symlink() or len(rows) != 1 or rows[0][2] != 'ext4':
            raise RuntimeError('Boot directory must be the mounted ext4 boot volume')
        opts = set(rows[0][3].split(','))
        if {'noload', 'norecovery'} & opts:
            raise RuntimeError('Reboot into the current Gemini system before updating boot files: the boot volume needs its journal enabled')
        if ('rw' if writable else 'ro') not in opts:
            raise RuntimeError('Boot volume is not mounted '+('read-write' if writable else 'read-only'))
        device = Path(unescape(rows[0][0]))
        expected = Path('/dev/disk/by-partlabel/linux')
        if not device.is_block_device() or device.stat().st_rdev != expected.stat().st_rdev:
            raise RuntimeError('Boot mount does not use the configured Linux partition')
        header = subprocess.check_output(['dumpe2fs', '-h', str(device)], text=True, stderr=subprocess.DEVNULL)
        features = [line.split(':', 1)[1].split() for line in header.splitlines() if line.startswith('Filesystem features:')]
        if len(features) != 1 or 'has_journal' not in features[0]:
            raise RuntimeError('Boot filesystem has no journal')

    @contextmanager
    def writable(self):
        self.require()
        # Always restore read-only, including a failed remount verification.
        try:
            subprocess.run(['mount', '-o', 'remount,rw', str(self.path)], check=True)
            self.require(writable=True)
            yield
        finally:
            os.sync()
            subprocess.run(['mount', '-o', 'remount,ro', str(self.path)], check=True)
            self.require()


def publish(mode, root, staging, previous=None, manager=None):
    command = ['sh', str(PUBLISH), mode, str(root), str(staging), str(staging/'files.manifest')]
    if previous is not None:
        command += [previous, manager or '']
    subprocess.run(command, check=True)


def protect_generation(system, entry, check=False):
    """Keep every installed entry bootable until profile cleanup removes it."""
    path = GENERATION_ROOTS/entry
    if path.is_symlink() and os.readlink(path) == system:
        return
    if path.exists() or path.is_symlink() or check:
        raise RuntimeError('Boot generation GC root is missing or differs: '+str(path))
    GENERATION_ROOTS.mkdir(parents=True, exist_ok=True)
    path.symlink_to(system)


def prune_generations(root, selected):
    # Only collect entries this installer rooted, and only when the standard
    # system profile exists. Recovery entries and manually installed files
    # have independent owners.
    profiles = list(SYSTEM_PROFILES.glob('system-*-link'))
    if not profiles:
        return
    retained = {str(p.resolve()) for p in profiles} | {selected}
    # Keep the current default bootable even if its profile was removed.
    # Once publication selects the new entry, the old one can be collected.
    config = checked_path(root, CONFIG)
    defaults = []
    if config.exists():
        defaults = [fields[1].lower() for line in regular(config).read_text().splitlines()
                    if len(fields := line.split()) == 2 and fields[0] == 'default']
    for link in GENERATION_ROOTS.iterdir():
        if not re.fullmatch(r'gemini-[0-9a-f]{64}\.conf', link.name) or not link.is_symlink():
            continue
        system = os.readlink(link)
        if system in retained or any(fnmatchcase(link.name.lower(), pattern) for pattern in defaults):
            continue
        identity = link.name[7:-5]
        directory = 'EFI/Gemini/'+identity
        entry = checked_path(root, 'loader/entries/'+link.name)
        if entry.exists():
            options = [line.split()[1:] for line in regular(entry).read_text().splitlines()
                       if line.startswith('options ')]
            if len(options) != 1 or [p for p in options[0] if p.startswith('init=')] != ['init='+system+'/init']:
                raise ValueError('Obsolete entry no longer belongs to its generation')
            entry.unlink()
        # Do not collect files another entry references, even if it was
        # created outside this installer.
        if any('/'+directory+'/' in p.read_text() for p in (root/'loader/entries').glob('*.conf')):
            continue
        for name in ('linux.efi', 'initrd.cpio.gz', 'gemini.dtb'):
            path = checked_path(root, directory+'/'+name)
            if path.exists():
                regular(path).unlink()
        directory_path = checked_path(root, directory)
        if directory_path.is_dir() and not any(directory_path.iterdir()):
            directory_path.rmdir()
        link.unlink()


def install(package, volume, store_image=None, check=False, system=False, manager=None):
    root = volume.path
    volume.require()
    with tempfile.TemporaryDirectory(prefix='gemini-boot-', dir='/run') as temporary:
        staging = Path(temporary)
        manifest = prepare_generation(package, staging, manager) if system else prepare(package, staging)
        store = manifest['store']
        persistent = store.get('root') == '/persist/nixos'
        if persistent:
            subprocess.run(['nix-store', '--check-validity', store['system']], check=True)
        destination = None if persistent else checked_path(root, 'nixos/'+store['file'])
        missing_store = destination is not None and not destination.exists()
        if destination is not None and not missing_store and not matches(destination, store):
            raise ValueError('Existing store image differs; it will not be overwritten')
        if missing_store and (store_image is None or not matches(regular(store_image), store)):
            raise ValueError('The matching squashfs is missing; provide --store-image from the system bundle')
        previous = checked_path(root, CONFIG)
        previous_sha = digest(regular(previous)) if previous.exists() else None
        manager = checked_path(root, MANAGER)
        manager_sha = digest(regular(manager)) if manager.exists() else None
        needed = store['size'] if missing_store else 0
        complete = not missing_store
        for name, info in manifest['files'].items():
            path = checked_path(root, name)
            equal = matches(path, info)
            complete = complete and equal
            if path.exists() and not equal and name not in (CONFIG, MANAGER):
                raise ValueError('Existing immutable boot file differs: '+name)
            if not equal:
                needed += info['size']
        if check:
            if not complete:
                raise RuntimeError('EFI generation is not installed and selected')
            if persistent:
                protect_generation(store['system'], manifest['entry'], check=True)
        elif not complete:
            if persistent and shutil.disk_usage(root).free < needed + 8 * 1024 * 1024:
                protect_generation(store['system'], manifest['entry'])
                with volume.writable():
                    prune_generations(root, store['system'])
            if shutil.disk_usage(root).free < needed + 8 * 1024 * 1024:
                raise RuntimeError('Not enough space on the boot volume; retained generations are preserved')
            if persistent:
                protect_generation(store['system'], manifest['entry'])
            with volume.writable():
                if missing_store:
                    parent = checked_path(root, 'nixos')
                    parent.mkdir(exist_ok=True)
                    fd, name = tempfile.mkstemp(prefix='.gemini-store-', dir=parent)
                    temporary_store = Path(name)
                    try:
                        with os.fdopen(fd, 'wb') as dst, store_image.open('rb') as src:
                            shutil.copyfileobj(src, dst, 1024 * 1024)
                            dst.flush()
                            os.fchmod(dst.fileno(), 0o644)
                            os.fsync(dst.fileno())
                        if not matches(temporary_store, store):
                            raise ValueError('Copied store image differs from the generation')
                        os.link(temporary_store, destination)
                    finally:
                        temporary_store.unlink()
                publish('activate' if previous_sha else 'install', root, staging, previous_sha, manager_sha)
                publish('verify', root, staging)
                if destination is not None and not matches(destination, store):
                    raise ValueError('Store image changed during installation')
            # Independent readback after restoring read-only.
            publish('verify', root, staging)
            if destination is not None and not matches(destination, store):
                raise ValueError('Store image readback failed')
        if persistent and not check:
            protect_generation(store['system'], manifest['entry'])
            with volume.writable():
                prune_generations(root, store['system'])
        return dict(entry=manifest['entry'], payload_identity=manifest['payload_identity'],
                    store_sha256=store.get('sha256'), system=store['system'],
                    previous_default_sha256=previous_sha, previous_manager_sha256=manager_sha,
                    changed=not complete and not check, read_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('efi_files', type=Path, help='Built efiBootFiles directory')
    parser.add_argument('--store-image', type=Path, help='Matching squashfs, if not already installed')
    parser.add_argument('--check', action='store_true', help='Verify the installed generation without writes')
    parser.add_argument('--json', action='store_true', help='Print the installation result as JSON')
    parser.add_argument('--system', action='store_true', help='Install a NixOS system generation (used by activation)')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Run gemini-boot-install as root')
    os.umask(0o077)
    with open('/run/lock/gemini-boot-install.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = install(args.efi_files.resolve(strict=True), BootVolume(Path('/gemian')),
                         args.store_image.resolve(strict=True) if args.store_image else None, args.check,
                         args.system, Path(os.environ['GEMINI_BOOT_MANAGER']) if args.system else None)
    print(json.dumps(result) if args.json else ('Verified ' if args.check else 'Installed ')+result['entry'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(str(error))
