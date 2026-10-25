#!/usr/bin/env python3
"""Static smoke checks, not a substitute for SAST, Android SDK builds or pentesting."""
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app/src/main'
MANIFEST = (APP / 'AndroidManifest.xml').read_text()
BRIDGE = (APP / 'java/com/novacinema/connect/WireGuardBridge.kt').read_text()
PROVISION = (APP / 'java/com/novacinema/connect/ProvisioningStore.kt').read_text()
PROBE = (ROOT / 'core/src/main/kotlin/com/novacinema/connect/core/JellyfinNetworkProbe.kt').read_text()
POLICY = (ROOT / 'core/src/main/kotlin/com/novacinema/connect/core/SecurityPolicies.kt').read_text()
CONNECTION = (ROOT / 'core/src/main/kotlin/com/novacinema/connect/core/ConnectionPolicy.kt').read_text()
checks = {
  'app backups off': 'android:allowBackup="false"' in MANIFEST,
  'cleartext traffic prohibited': 'android:usesCleartextTraffic="false"' in MANIFEST,
  'VPN restricted to NOVA Android package': 'includedApplications == setOf(installedPackageName)' in BRIDGE,
  'VPN route matches exact private gateway': 'RouteGuard.allowedHostRoutes(allAllowed, setOf(urlHost))' in BRIDGE,
  'no public or broad LAN routes accepted': 'fields[1] == "32"' in POLICY,
  'no public LAN fallback': 'EndpointValidator.isValidPrivateLan(it)' in CONNECTION,
  'certificate failures are not classified offline': 'catch (_: SSLException)' in PROBE and 'TLS_VALIDATION_FAILED' in PROBE,
  'Jellyfin server identity pinned': 'expectedServerId' in PROBE and 'expectedServerId' in PROVISION,
  'encryption backed by Android Keystore': 'AndroidKeyStore' in PROVISION and 'AES/GCM/NoPadding' in PROVISION,
    'no hostname verifier override': not any('HostnameVerifier' in s for s in (APP/'java').rglob('*.kt') for s in [s.read_text(encoding='utf8')]),
}
all_sources='\n'.join(f.read_text(errors='replace') for f in (ROOT/'app/src/main/java').rglob('*.kt'))
all_sources+='\n'+'\n'.join(f.read_text(errors='replace') for f in (ROOT/'core/src/main/kotlin').rglob('*.kt'))
checks['no embedded PEM private key'] = not re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',all_sources)
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ' ' + name)
print(f"Heuristic source checks: {sum(checks.values())}/{len(checks)} passed")
if not all(checks.values()):
    raise SystemExit(1)
