#!/usr/bin/env bash
# Rebuild only the prerequisites and external module; never contact a router.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:?source directory required}"
OUT="${2:?output directory required}"
JOBS="${BUILD_JOBS:-2}"
case "$JOBS" in 2|4) ;; *) echo 'BUILD_JOBS must be 2 or 4' >&2; exit 2 ;; esac
[[ "${RESCUE_LAYOUT:-linux-original-474m}" == linux-original-474m ]] || { echo 'Module reference requires linux-original-474m'; exit 2; }
mkdir -p "$OUT/logs"
SRC="$(cd "$SRC" && pwd)"
OUT="$(cd "$OUT" && pwd)"
[[ "$(id -u)" != 0 ]] || { echo 'Build as a normal user'; exit 2; }
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
phase prepare python3 "$ROOT/scripts/rescue.py" prepare --source "$SRC" --out "$OUT" --layout linux-original-474m
# Restore the exact known-good configuration, then select only the external module.
cp "$OUT/reference/reference.config" .config
phase baseline-defconfig timeout 10m make defconfig
cp .config "$OUT/baseline.config"
cp tmp/.packageinfo "$OUT/packageinfo.txt"
phase configuration-check python3 "$ROOT/scripts/rescue.py" check-config --source "$SRC"
sed -i 's/^# CONFIG_PACKAGE_kmod-mtd-rw is not set$/CONFIG_PACKAGE_kmod-mtd-rw=m/' .config
phase module-defconfig timeout 10m make defconfig
cp .config "$OUT/expanded.config"
phase config-delta-check python3 "$ROOT/scripts/module_reference.py" check-config \
    --before "$OUT/reference/reference.config" --after .config
phase download timeout 40m make download -j4
phase build-tools timeout --signal=TERM --kill-after=2m 90m make -j"$JOBS" tools/install V=s
phase build-toolchain timeout --signal=TERM --kill-after=2m 100m make -j"$JOBS" toolchain/install V=s
phase build-kernel timeout --signal=TERM --kill-after=2m 100m make -j"$JOBS" target/linux/compile V=s
shopt -s nullglob
kernels=(build_dir/target-*/linux-mediatek_filogic/linux-6.6.133)
[[ "${#kernels[@]}" == 1 ]] || { echo 'Expected exactly one 6.6.133 kernel build'; exit 1; }
KERNEL="${kernels[0]}"
cp "$KERNEL/.config" "$OUT/kernel.config"
cp "$KERNEL/.vermagic" "$OUT/kernel-abi.txt"
cp "$KERNEL/Module.symvers" "$OUT/kernel-Module.symvers.txt"
[[ "$(cat "$KERNEL/.vermagic")" == 030ad1570833e99b365a217a0ba91204 ]] || { echo 'Kernel ABI differs from the running rescue; refusing module delivery'; exit 1; }
phase build-module timeout --signal=TERM --kill-after=2m 20m make -j"$JOBS" package/feeds/packages/mtd-rw/compile V=s
mapfile -d '' packages < <(find bin -type f -name 'kmod-mtd-rw_*.ipk' -print0)
[[ "${#packages[@]}" == 1 ]] || { echo 'Expected exactly one kmod-mtd-rw package'; exit 1; }
phase validate-module python3 "$ROOT/scripts/validate_mtd_module.py" \
    --ipk "${packages[0]}" --reference-module "$OUT/reference/reference.ko" \
    --kernel-build "$KERNEL" --out "$OUT/validated"
cp "$ROOT/docs/mtd-module.md" "$OUT/validated/README.md"
cp "$OUT/reference/reference.json" "$OUT/validated/reference.json"
cp "$OUT/source-lock.json" "$OUT/validated/source-lock.json"
cp "$OUT/expanded.config" "$OUT/validated/build.config"
cp "$OUT/kernel.config" "$OUT/validated/kernel.config"
cp "$OUT/kernel-compatibility.json" "$OUT/validated/kernel-compatibility.json"
cp "$OUT/9999-99-n60pro-rescue-no-hnat.patch" "$OUT/validated/9999-99-n60pro-rescue-no-hnat.patch"
git -C "$SRC" diff --binary > "$OUT/validated/source.patch"
(
    cd "$OUT/validated"
    sha256sum -- * > "$OUT/SHA256SUMS.module"
    cp "$OUT/SHA256SUMS.module" SHA256SUMS
)
