#!/usr/bin/env python3
"""Import automatic ConnMan profiles once, without exposing their secrets."""
import configparser
import hashlib
import os
from pathlib import Path
import re
import uuid


def keyfile_string(value):
    escapes = {'s': ' ', 'n': '\n', 't': '\t', 'r': '\r', '\\': '\\'}
    if re.search(r'\\(?:[^sntr\\]|$)', value):
        raise ValueError('invalid-keyfile-escape')
    return re.sub(r'\\(.)', lambda m: escapes[m[1]], value)


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
            contents = (
                f'[connection]\nid=Gemian Wi-Fi {identity[:8]}\nuuid={identity}\n'
                'type=wifi\nautoconnect=true\n\n'
                '[wifi]\nmode=infrastructure\n'
                f'ssid={";".join(str(byte) for byte in ssid)};\n\n'
                '[wifi-security]\nkey-mgmt=wpa-psk\n'
                f'psk={psk}\n\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n'
            )
            # Never overwrite a profile subsequently edited in GNOME.
            try:
                descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w') as stream:
                    stream.write(contents)
                imported += 1
            except FileExistsError:
                pass
        except (OSError, ValueError, KeyError, configparser.Error):
            # Exception text and filenames may contain private profile material.
            print('Skipped an unreadable or unsupported saved Wi-Fi profile')
    print(f'Imported {imported} saved Wi-Fi profile(s)')


if __name__ == '__main__':
    import_profiles(Path('/gemian/var/lib/connman'),
                    Path('/persist/NetworkManager/system-connections'))
