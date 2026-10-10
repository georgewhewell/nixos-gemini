#!/usr/bin/env python3
"""Import automatic ConnMan profiles once, without exposing their secrets."""
import configparser
import hashlib
import os
from pathlib import Path
import re
import tempfile
import uuid


def keyfile_string(value):
    escapes = {'s': ' ', 'n': '\n', 't': '\t', 'r': '\r', '\\': '\\'}
    if re.search(r'\\(?:[^sntr\\]|$)', value):
        raise ValueError('invalid-keyfile-escape')
    return re.sub(r'\\(.)', lambda m: escapes[m[1]], value)


def keyfile_escape(value):
    return ''.join({'\\': '\\\\', ' ': '\\s', '\n': '\\n',
                    '\t': '\\t', '\r': '\\r'}.get(char, char) for char in value)


def connection_name(ssid, identity):
    try:
        name = ssid.decode('utf-8')
        if name.isprintable() and name.strip():
            return name
    except UnicodeDecodeError:
        pass
    return f'Wi-Fi network {identity[:8]}'


def update_generated_name(output, identity, encoded_ssid, name):
    """Rename only our old generated label, keeping desktop edits byte-exact."""
    if output.stat().st_size > 65536 or output.is_symlink():
        return
    text = output.read_bytes().decode('utf-8')
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    if (parser.get('connection', 'uuid', fallback='') != identity or
            parser.get('connection', 'type', fallback='') != 'wifi' or
            parser.get('connection', 'id', fallback='') != f'Gemian Wi-Fi {identity[:8]}' or
            parser.get('wifi', 'ssid', fallback='') != encoded_ssid):
        return
    # Change just the generated id line inside its section. Do not serialize
    # the parser: that would rewrite user settings, comments and credentials.
    section = re.search(r'(?m)^\[connection\][ \t]*\r?\n(?:(?!\[)[^\n]*\n)*', text)
    if not section:
        return
    updated, count = re.subn(r'(?m)^id=[^\r\n]*', lambda _: 'id=' + keyfile_escape(name),
                            section.group(), count=1)
    if count != 1:
        return
    contents = text[:section.start()] + updated + text[section.end():]
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=output.parent,
                                         prefix='.gemian-profile-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def import_profiles(source, destination):
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination, 0o700)
    imported = 0
    for path in sorted(source.glob('wifi_*_managed_psk/settings')):
        try:
            if path.stat().st_size > 65536:
                continue
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(path.read_text())
            if len(parser.sections()) != 1:
                continue
            profile = parser[parser.sections()[0]]
            if profile.get('Favorite') != 'true' or profile.get('AutoConnect') != 'true':
                continue
            encoded = profile.get('SSID', '')
            if not re.fullmatch(r'(?:[0-9a-fA-F]{2}){1,32}', encoded):
                continue
            ssid = bytes.fromhex(encoded)
            secret = keyfile_string(profile['Passphrase'])
            if re.fullmatch(r'[0-9a-fA-F]{64}', secret):
                psk = secret.lower()
            else:
                password = secret.encode('utf-8')
                if not 8 <= len(password) <= 63 or b'\0' in password:
                    continue
                psk = hashlib.pbkdf2_hmac('sha1', password, ssid, 4096, 32).hex()
            identity = str(uuid.uuid5(uuid.NAMESPACE_URL, 'gemini-wifi:' + ssid.hex()))
            output = destination / f'gemian-{identity}.nmconnection'
            name = connection_name(ssid, identity)
            encoded_ssid = ';'.join(str(byte) for byte in ssid) + ';'
            contents = (
                f'[connection]\nid={keyfile_escape(name)}\nuuid={identity}\n'
                'type=wifi\nautoconnect=true\n\n'
                '[wifi]\nmode=infrastructure\n'
                f'ssid={encoded_ssid}\n\n'
                '[wifi-security]\nkey-mgmt=wpa-psk\n'
                f'psk={psk}\n\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n'
            )
            # Retain desktop edits; old generated labels alone may migrate.
            try:
                descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w') as stream:
                    stream.write(contents)
                imported += 1
            except FileExistsError:
                update_generated_name(output, identity, encoded_ssid, name)
        except (OSError, ValueError, KeyError, configparser.Error):
            # Exception text and filenames may contain private profile material.
            print('Skipped an unreadable or unsupported saved Wi-Fi profile')
    print(f'Imported {imported} saved Wi-Fi profile(s)')


if __name__ == '__main__':
    import_profiles(Path('/gemian/var/lib/connman'),
                    Path('/persist/NetworkManager/system-connections'))
