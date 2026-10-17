#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/.build"
mapfile -t sources < <(find "$ROOT/core/src" -name '*.kt' -print | sort)
kotlinc "${sources[@]}" -include-runtime -d "$ROOT/.build/nova-core-tests.jar"
java -jar "$ROOT/.build/nova-core-tests.jar"
