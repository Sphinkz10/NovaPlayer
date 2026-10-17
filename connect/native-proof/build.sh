#!/usr/bin/env bash
# Compile-only M0 spike: no enrollment, accounts, tunnels or claims of network success.
set -euo pipefail
root="$(pwd)"
output="$root/native-output"
work="$(mktemp -d)"
mkdir -p "$output"
export ANDROID_NDK_HOME="$ANDROID_HOME/ndk/23.1.7779620"
export GOBIN="$work/tools"
export PATH="$GOBIN:$PATH"

fetch_source() {
    git init "$work/$1"
    git -C "$work/$1" remote add origin "$2"
    git -C "$work/$1" fetch --depth=1 origin "$3"
    git -C "$work/$1" checkout --detach FETCH_HEAD
    test "$(git -C "$work/$1" rev-parse HEAD)" = "$3"
}
fetch_source tailscale https://github.com/tailscale/tailscale-android.git 264102cc702fbd844e900227ee02e5cbb4d7f801
fetch_source netbird https://github.com/netbirdio/netbird.git 01185ba3536bcc037481578420d73cb7cee96094

cd "$work"
go work init ./tailscale ./netbird
# Use the exact mobile generator pinned by the NetBird source; both packages bind
# in ONE invocation, avoiding duplicate go.Seq classes and libgojni.so in the APK.
mobile=v0.0.0-20260816165457-f98cc9b3c733
go install "golang.org/x/mobile/cmd/gomobile@$mobile"
go install "golang.org/x/mobile/cmd/gobind@$mobile"
cp go.work "$output/"
cp tailscale/go.mod "$output/tailscale.go.mod"
cp netbird/go.mod "$output/netbird.go.mod"
cp tailscale/LICENSE "$output/TAILSCALE-LICENSE"
cp netbird/LICENSE "$output/NETBIRD-LICENSE"
# Preserve the list of resolved modules and hashes even if compilation fails.
trap 'cp -f "$work/go.work.sum" "$output/" 2>/dev/null || true' EXIT
go list -m -json all > "$output/modules.json"
gomobile bind -target=android/arm64,android/arm,android/amd64 -androidapi=26 \
  -javapkg=com.novacinema.engines -tags=ts_omit_cachenetmap \
  -ldflags="-linkmode=external -extldflags=-Wl,-z,max-page-size=16384 -checklinkname=0 -X golang.zx2c4.com/wireguard/ipc.socketDirectory=/data/data/com.novacinema.connect.poc/cache/wireguard" \
  -o "$output/nova-engines.aar" \
  github.com/tailscale/tailscale-android/libtailscale \
  github.com/netbirdio/netbird/client/android 2>&1 | tee "$output/build.log"
sha256sum "$output/nova-engines.aar" > "$output/SHA256SUMS.txt"
unzip -l "$output/nova-engines.aar" > "$output/aar-contents.txt"
