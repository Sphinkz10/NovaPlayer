"""Capture only exception types and stack locations, never messages or native memory."""
import json
import re
import subprocess


def capture(destination):
    raw = subprocess.run(['adb', 'logcat', '-b', 'crash', '-d', '-v', 'brief'],
                         capture_output=True, text=True, timeout=20).stdout
    entries = []
    for line in raw.splitlines():
        frame = re.search(r'\bat ((?:com\.novacinema|androidx\.media3|android\.|java\.|kotlin\.)[A-Za-z0-9_.$]+\([A-Za-z0-9_.: -]+\))', line)
        kind = re.search(r'\b((?:[a-zA-Z_]\w*\.)+[A-Za-z_][\w$]*(?:Exception|Error))\b', line)
        signal = re.search(r'\bsignal (\d+) \((SIG[A-Z]+)\)', line)
        if frame:
            entries.append({'frame': frame[1]})
        elif kind:
            entries.append({'type': kind[1]})
        elif signal:
            entries.append({'signal': signal[2]})
    destination.write_text(json.dumps({'crash_frames': entries[-80:]}, indent=2)+'\n', encoding='utf8')
