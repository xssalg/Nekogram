#!/usr/bin/env python3
"""Verify a server-issued login QR using an existing APK and private proxy.

Does not enter a phone number, send an SMS or authorize a user account.
Proxy values and decoded login tokens must never be written to artifacts.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import urllib.parse
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
import zxingcpp

OUT = Path('qr-login-check')
OUT.mkdir(exist_ok=True)
PACKAGE = 'tw.nekomimi.nekogram.personal'
COMPONENT = PACKAGE + '/org.telegram.ui.LaunchActivity'
proxy = json.loads(os.environ['NEKO_QR_CHECK_PROXY'])
private_values = [str(proxy[k]) for k in ('host', 'user', 'password')]
private_values += [urllib.parse.quote(v, safe='') for v in private_values]
private_values.append(base64.b64encode((proxy['user'] + ':' + proxy['password']).encode()).decode())
result = {'status': 'in_progress', 'stage': 'verify_apk', 'proxy_enabled_by_ui': False,
          'account_authorized': False, 'phone_or_sms_requested': False}


def redact(text):
    text = re.sub(r'tg://(?:httpproxy|login)[^\s<>"\']*', '[PRIVATE_URI]', text)
    for value in sorted(set(private_values), key=len, reverse=True):
        if value:
            text = text.replace(value, '[REDACTED]')
    return text


def adb(*args, binary=False, timeout=30):
    p = subprocess.run(['adb', *args], capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError('adb command failed: ' + redact(p.stderr.decode(errors='replace')))
    return p.stdout if binary else p.stdout.decode(errors='replace')


def shell(*args, timeout=30):
    # adb shell concatenates arguments; quote the complete remote command.
    return adb('shell', shlex.join([str(a) for a in args]), timeout=timeout)


def hierarchy():
    shell('uiautomator', 'dump', '--compressed', '/sdcard/qr-check-ui.xml')
    return ET.fromstring(adb('exec-out', 'cat', '/sdcard/qr-check-ui.xml'))


def nodes():
    return list(hierarchy().iter('node'))


def tap_label(label, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for node in nodes():
            if label.casefold() in [node.get('text', '').casefold(), node.get('content-desc', '').casefold()]:
                bounds = [int(x) for x in re.findall(r'\d+', node.get('bounds', ''))]
                if len(bounds) == 4 and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
                    shell('input', 'tap', (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
                    print('TAPPED', label, flush=True)
                    time.sleep(1)
                    return
        time.sleep(1)
    raise RuntimeError('UI control not found: ' + label)


def capture_safe():
    root = hierarchy()
    img = Image.open(io.BytesIO(adb('exec-out', 'screencap', '-p', binary=True))).convert('RGB')
    draw = ImageDraw.Draw(img)
    if result['stage'] not in ('await_server_login_token', 'decoded_login_qr'):
        # Proxy import controls can show credentials outside accessibility nodes.
        draw.rectangle((0, 0, img.width, img.height), fill='white')
    labels = []
    for node in root.iter('node'):
        content = node.get('text', '') + ' ' + node.get('content-desc', '')
        if any(v and v in content for v in private_values):
            bounds = [int(x) for x in re.findall(r'\d+', node.get('bounds', ''))]
            if len(bounds) == 4:
                draw.rectangle(bounds, fill='gray')
        if content.strip():
            labels.append(redact(content.strip()))
    (OUT / 'visible-labels.json').write_text(json.dumps(labels, indent=2))
    (OUT / 'ui.xml').write_text(redact(ET.tostring(root, encoding='unicode')))
    if not (OUT / 'screen.png').exists():
        img.save(OUT / 'screen.png')


try:
    apks = list(Path('artifacts').glob('*.apk'))
    assert len(apks) == 1, 'Expected one signed APK'
    apk = apks[0]
    result['apk_sha256'] = hashlib.sha256(apk.read_bytes()).hexdigest()
    expected = os.environ.get('EXPECTED_APK_SHA256', '').strip()
    if not expected:
        expected = Path(str(apk) + '.sha256').read_text().split()[0]
    assert result['apk_sha256'] == expected, 'APK checksum mismatch'
    result['stage'] = 'install_and_start'
    adb('install', '-r', str(apk), timeout=180)
    # The disposable emulator has a virtual SIM. Avoid its first-run autofill
    # permission dialog covering the login menu; no phone number is submitted.
    for permission in ('READ_PHONE_STATE', 'READ_PHONE_NUMBERS'):
        shell('pm', 'grant', PACKAGE, 'android.permission.' + permission)
    adb('logcat', '-c')
    shell('am', 'start', '-W', '-n', COMPONENT, timeout=90)
    tap_label('Start Messaging')
    result['stage'] = 'import_proxy'
    uri = 'tg://httpproxy?' + urllib.parse.urlencode({
        'server': proxy['host'], 'port': proxy['port'], 'user': proxy['user'], 'pass': proxy['password']})
    shell('am', 'start', '-W', '-a', 'android.intent.action.VIEW', '-n', COMPONENT, '-d', uri)
    tap_label('Connect Proxy')
    result['proxy_enabled_by_ui'] = True
    result['stage'] = 'open_qr_login'
    tap_label('More options')
    tap_label('QR Login')
    result['stage'] = 'await_server_login_token'
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        png = adb('exec-out', 'screencap', '-p', binary=True)
        img = Image.open(io.BytesIO(png))
        decoded = zxingcpp.read_barcodes(img)
        valid = []
        for barcode in decoded:
            url = urllib.parse.urlparse(barcode.text)
            token = urllib.parse.parse_qs(url.query).get('token', [''])[0]
            if url.scheme == 'tg' and url.netloc == 'login' and token:
                valid.append(token)
        if valid:
            (OUT / 'screen.png').write_bytes(png)
            result.update(status='success', stage='decoded_login_qr', qr_payload_type='tg://login?token',
                          token_character_count=len(valid[0]), first_frame_and_qr_decoded=True)
            break
        time.sleep(4)
    else:
        raise RuntimeError('No server-issued login QR decoded within 120 seconds')
except Exception as e:
    result.update(status='failure', error=redact(type(e).__name__ + ': ' + str(e)))
finally:
    try:
        capture_safe()
        (OUT / 'logcat.txt').write_text(redact(adb('logcat', '-d')))
    except Exception as e:
        result['capture_error'] = redact(type(e).__name__ + ': ' + str(e))
    try:
        shell('am', 'force-stop', PACKAGE)
    except Exception:
        pass
    (OUT / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)

raise SystemExit(0 if result['status'] == 'success' else 1)
