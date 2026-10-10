#!/usr/bin/env python3
"""Own a saved WPA2 connection after the Gemini boot has been accepted.

WPA2 connects with ap_scan=2 after a fresh passive scan. Keep retries
outside boot acceptance; profile contents and supplicant output stay in /run.
GEMINI_WIFI_SAE=prefer opts into WPA3-SAE (with PMF) for APs that offer SAE
when the saved profile holds the passphrase; the default keeps WPA2-PSK.
SAE uses ap_scan=1: wpa_supplicant must hold the AP's own scan result (its
RSN element) before it will connect with PMF required.
"""

import configparser
import hashlib
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time


WORK = Path('/run/gemini-wifi')
STOP = threading.Event()
SAE = os.environ.get('GEMINI_WIFI_SAE', 'off') == 'prefer'


class Unavailable(Exception):
    """A retryable condition whose message contains no private data."""


def keyfile_string(value):
    escapes = {'s': ' ', 'n': '\n', 't': '\t', 'r': '\r', '\\': '\\'}
    result = []
    pos = 0
    while pos < len(value):
        char = value[pos]
        pos += 1
        if char == '\\':
            if pos == len(value) or value[pos] not in escapes:
                raise ValueError('invalid-keyfile-escape')
            char = escapes[value[pos]]
            pos += 1
        result.append(char)
    return ''.join(result)


def read_profile(path):
    if path.stat().st_size > 65536:
        raise ValueError('oversized-profile')
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text())
    if len(parser.sections()) != 1:
        raise ValueError('profile-sections')
    section = parser[parser.sections()[0]]
    if section.get('Favorite') != 'true' or section.get('AutoConnect') != 'true':
        return None
    encoded = section.get('SSID', '')
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}){1,32}', encoded):
        raise ValueError('profile-ssid')
    ssid = bytes.fromhex(encoded)
    secret = keyfile_string(section['Passphrase'])
    if re.fullmatch(r'[0-9a-fA-F]{64}', secret):
        psk = secret.lower()
        password = None  # A raw PSK cannot drive SAE.
    else:
        password = secret.encode('utf-8')
        if not 8 <= len(password) <= 63 or b'\x00' in password:
            raise ValueError('profile-passphrase')
        psk = hashlib.pbkdf2_hmac('sha1', password, ssid, 4096, 32).hex()
    return ssid, psk, password


def iw_ssid(value):
    # iw escapes nonprintable bytes, backslash and leading/trailing spaces.
    result = bytearray()
    pos = 0
    while pos < len(value):
        if value[pos:pos + 2] == b'\\x':
            if not re.fullmatch(b'[0-9a-fA-F]{2}', value[pos + 2:pos + 4]):
                raise ValueError('scan-ssid-escape')
            result.append(int(value[pos + 2:pos + 4], 16))
            pos += 4
        else:
            result.append(value[pos])
            pos += 1
    return bytes(result)


def scan_candidates(scan):
    candidates = []
    for block in re.split(rb'(?m)^BSS ', scan)[1:]:
        address = re.match(rb'([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})(?:\(|\s)', block)
        frequency = re.search(rb'(?m)^\s*freq: (\d+)$', block)
        strength = re.search(rb'(?m)^\s*signal: (-?[0-9.]+) dBm$', block)
        name = re.search(rb'(?m)^\tSSID: (.*)$', block)
        rsn = re.search(rb'(?m)^\tRSN:[^\n]*\n((?:\t\t.*\n?)*)', block)
        if not all((address, frequency, strength, name, rsn)):
            continue
        freq = int(frequency[1])
        if freq not in range(2412, 2463, 5):
            continue
        security = rsn[1]
        if not re.search(rb'(?m)^\t\t *\* Group cipher: CCMP$', security):
            continue
        if not re.search(rb'(?m)^\t\t *\* Pairwise ciphers:.*(?:^| )CCMP(?: |$)', security):
            continue
        psk = (re.search(rb'(?m)^\t\t *\* Authentication suites:.*(?:^| )PSK(?: |$)', security)
               and b'MFP-required' not in security)
        sae = SAE and re.search(rb'(?m)^\t\t *\* Authentication suites:.*(?:^| )SAE(?: |$)', security)
        if not psk and not sae:
            continue
        try:
            ssid = iw_ssid(name[1])
            signal_dbm = float(strength[1])
        except ValueError:
            continue
        candidates.append((ssid, address[1].decode('ascii'), signal_dbm, bool(psk), bool(sae)))
    return candidates


def choose_network(paths, candidates):
    visible = {entry[0] for entry in candidates}
    eligible = set()
    for path in paths:
        try:
            profile = read_profile(path)
        except (OSError, ValueError, KeyError, configparser.Error):
            continue
        if profile is not None and profile[0] in visible:
            eligible.add(profile)
    if len(eligible) != 1:
        raise Unavailable('no-unique-visible-saved-network')
    ssid, psk, password = eligible.pop()
    entries = [entry for entry in candidates if entry[0] == ssid]
    if SAE and password is not None:
        sae = [entry for entry in entries if entry[4]]
        if sae:
            return ssid, password, max(sae, key=lambda entry: entry[2])[1], True
    entries = [entry for entry in entries if entry[3]]
    if not entries:
        raise Unavailable('no-supported-security')
    return ssid, psk, max(entries, key=lambda entry: entry[2])[1], False


def configuration(ssid, secret, bssid, control, sae=False):
    if (not 1 <= len(ssid) <= 32
            or not re.fullmatch(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}', bssid)
            or not re.fullmatch(r'/[a-zA-Z0-9_/-]+', control)):
        raise ValueError('configuration-input')
    if sae:
        if not isinstance(secret, bytes) or not 8 <= len(secret) <= 63:
            raise ValueError('configuration-input')
        # WPA3-Personal: SAE (hunting-and-pecking or hash-to-element) with
        # required PMF; the hex password avoids config-file quoting.
        return (f'ctrl_interface={control}\nap_scan=1\nsae_pwe=2\nnetwork={{\n'
                f'\tssid={ssid.hex()}\n\tsae_password={secret.hex()}\n\tbssid={bssid}\n'
                '\tproto=RSN\n\tkey_mgmt=SAE\n\tpairwise=CCMP\n'
                '\tgroup=CCMP\n\tgroup_mgmt=AES-128-CMAC\n\tieee80211w=2\n}\n')
    if not isinstance(secret, str) or not re.fullmatch(r'[0-9a-f]{64}', secret):
        raise ValueError('configuration-input')
    return (f'ctrl_interface={control}\nap_scan=2\nnetwork={{\n'
            f'\tssid={ssid.hex()}\n\tpsk={secret}\n\tbssid={bssid}\n'
            '\tproto=RSN\n\tkey_mgmt=WPA-PSK\n\tpairwise=CCMP\n'
            '\tgroup=CCMP\n\tieee80211w=0\n}\n')


def state(value):
    (WORK / 'state').write_text(value + '\n')
    print('wifi=' + value, flush=True)


def run(args, timeout):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=timeout, check=True).stdout


def status(interface):
    try:
        output = run(['wpa_cli', '-p', str(WORK / 'ctrl'), '-i', interface, 'status'], 3)
    except (subprocess.SubprocessError, OSError):
        return ''
    for line in output.splitlines():
        if line.startswith(b'wpa_state='):
            return line[10:].decode('ascii', errors='replace')
    return ''


def stop_child(child):
    # Popen owns this exact process; never kill by name or reload CONSYS.
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def connect(interface):
    state('scanning')
    scan = run(['iw', 'dev', interface, 'scan', 'passive'], 70)
    candidates = scan_candidates(scan)
    ssid, secret, bssid, sae = choose_network(
        Path('/gemian/var/lib/connman').glob('wifi_*_managed_psk/settings'), candidates)
    (WORK / 'wpa.conf').write_text(configuration(ssid, secret, bssid, str(WORK / 'ctrl'), sae))
    state('connecting-sae' if sae else 'connecting')
    with (WORK / 'supplicant.log').open('wb') as log:
        child = subprocess.Popen(['wpa_supplicant', '-D', 'nl80211', '-i', interface,
                                  '-c', str(WORK / 'wpa.conf')],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        (WORK / 'pid').write_text(str(child.pid) + '\n')
        try:
            deadline = time.monotonic() + 45
            connected = False
            while not STOP.wait(1):
                if child.poll() is not None:
                    raise Unavailable('supplicant-exited')
                current = status(interface)
                if current == 'COMPLETED':
                    if not connected:
                        connected = True
                        state('connected')
                    deadline = time.monotonic() + 5
                elif time.monotonic() >= deadline:
                    raise Unavailable('connection-lost' if connected else 'connection-timeout')
        finally:
            stop_child(child)
            (WORK / 'pid').unlink(missing_ok=True)
            (WORK / 'wpa.conf').unlink(missing_ok=True)


def main():
    os.umask(0o077)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    WORK.mkdir(mode=0o700, exist_ok=True)
    os.chmod(WORK, 0o700)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    (WORK / 'boot-id').write_text(boot + '\n')
    state('waiting-for-acceptance')
    while not STOP.is_set():
        try:
            accepted = Path('/run/unattended-recovery.accepted').read_text().strip()
            ready_boot = Path('/run/gemini-connectivity/boot-id').read_text().strip()
            ready = Path('/run/gemini-connectivity/result').read_text().strip()
            if accepted == 'unattended_recovery=healthy' and ready_boot == boot and ready == 'connectivity=firmware-ready':
                break
        except OSError:
            pass
        STOP.wait(2)
    if STOP.is_set():
        return
    interface = Path('/run/gemini-connectivity/interface').read_text().strip()
    if (not re.fullmatch(r'[a-zA-Z0-9_-]+', interface)
            or not Path('/sys/bus/platform/devices/180f0000.wifi/net', interface).is_dir()):
        raise ValueError('interface-owner')
    while not STOP.is_set():
        try:
            connect(interface)
        except Unavailable as error:
            state(str(error))
        except Exception as error:
            # Exception text can contain profile material or process arguments.
            state('retry-' + type(error).__name__)
        if not STOP.is_set():
            STOP.wait(30)
    state('stopped')


if __name__ == '__main__':
    main()
