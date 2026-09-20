#!/usr/bin/env bash
# No automatic full retry or clean rebuild on failure. Keep the original error log.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:?source directory required}"
OUT="${2:?output directory required}"
LAYOUT="${3:-linux-original-474m}"
JOBS="${BUILD_JOBS:-2}"
case "$JOBS" in 2|4) ;; *) echo 'BUILD_JOBS must be 2 or 4' >&2; exit 2 ;; esac
mkdir -p "$OUT/logs"
SRC="$(cd "$SRC" && pwd)"
OUT="$(cd "$OUT" && pwd)"
[[ "$SRC" != *' '* && "$ROOT" != *' '* ]] || { echo 'Build paths cannot contain spaces'; exit 2; }
[[ "$(id -u)" != 0 ]] || { echo 'Build as a normal user, not root'; exit 2; }
cd "$SRC"
export TZ=UTC LC_ALL=C.UTF-8
export SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)"
phase() {
    local name="$1"; shift
    echo "===== $name ====="
    "$@" 2>&1 | tee "$OUT/logs/$name.log"
}
phase feeds-index timeout 20m ./scripts/feeds update -a
phase feeds-install timeout 20m ./scripts/feeds install -a
phase prepare python3 "$ROOT/scripts/rescue.py" prepare --source "$SRC" --out "$OUT" --layout "$LAYOUT"
phase defconfig timeout 10m make defconfig
phase configuration-check python3 "$ROOT/scripts/rescue.py" check-config --source "$SRC"
cp .config "$OUT/expanded.config"
# Limited parallel download. A real error stops the run; no blanket rerun at -j1.
phase download timeout 40m make download -j4
phase compile timeout --signal=TERM --kill-after=2m 250m make -j"$JOBS" V=s
phase package timeout 15m python3 "$ROOT/scripts/rescue.py" package --source "$SRC" --out "$OUT" --layout "$LAYOUT"
