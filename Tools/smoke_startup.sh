#!/usr/bin/env bash
set -euo pipefail
mkdir -p startup-smoke
capture_diagnostics() {
  adb shell dumpsys activity activities > startup-smoke/activities.txt || true
  adb logcat -d > startup-smoke/logcat.txt || true
  adb exec-out screencap -p > startup-smoke/screen.png || true
}
trap capture_diagnostics EXIT
adb shell getprop ro.product.cpu.abilist | tee startup-smoke/abis.txt
apk=$(find artifacts -name '*.apk' -print -quit)
test -n "$apk"
adb install -r "$apk"
adb logcat -c
adb shell am start -W -n tw.nekomimi.nekogram.personal/org.telegram.ui.LaunchActivity | tee startup-smoke/launch.txt
sleep 20
adb shell pidof tw.nekomimi.nekogram.personal | tee startup-smoke/pid.txt
test -s startup-smoke/pid.txt
adb shell dumpsys activity activities > startup-smoke/activities.txt
adb logcat -d > startup-smoke/logcat.txt
adb exec-out screencap -p > startup-smoke/screen.png
python3 - <<'PY'
from pathlib import Path
p=Path('startup-smoke')
assert 'Status: ok' in (p/'launch.txt').read_text(), 'Activity launch did not complete'
lines=(p/'activities.txt').read_text().splitlines()
assert any('mResumedActivity' in line and 'tw.nekomimi.nekogram.personal' in line for line in lines), 'App is not resumed after startup'
assert 'Displayed tw.nekomimi.nekogram.personal/' in (p/'logcat.txt').read_text(), 'First application frame was not displayed'
print('PASS personal APK launched, drew its first frame and remained alive after 20 seconds')
PY
