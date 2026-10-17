"""Run only against the disposable CI emulator; no VPN or credentials."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "native-output" / "runtime"
OUT.mkdir(parents=True, exist_ok=True)


def adb(*args, timeout=90):
    return subprocess.run(["adb", *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout).stdout


def run():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This destructive app-install smoke test is scoped to the CI emulator.")
    if adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise SystemExit("Refusing to use a physical device.")
    app = ROOT / "connect/app/build/outputs/apk/debug/app-debug.apk"
    test = ROOT / "connect/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
    for apk in (app, test):
        adb("install", "-r", "-t", str(apk), timeout=180)
    results = []
    try:
        for order in ("wireguard-first", "gomobile-first"):
            adb("shell", "am", "force-stop", "com.novacinema.connect.poc")
            output = adb("shell", "am", "instrument", "-w", "-r", "-e", "order", order,
                         "com.novacinema.connect.poc.test/com.novacinema.connect.NativeEngineSmokeInstrumentation")
            (OUT / (order + ".txt")).write_text(output, encoding="utf8")
            assert "INSTRUMENTATION_RESULT: nova_native_smoke=passed" in output, output
            assert "INSTRUMENTATION_CODE: -1" in output, output
            assert "INSTRUMENTATION_RESULT: order=" + order in output, output
            results.append({"order": order, "result": "passed"})
        (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf8")
        print(json.dumps({"native_runtime": results, "tunnel_tested": False}))
    finally:
        (OUT / "logcat.txt").write_text(adb("logcat", "-d", "-t", "500"), encoding="utf8")


if __name__ == "__main__":
    run()
