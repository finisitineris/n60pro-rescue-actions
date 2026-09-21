# Validation of the 2026-09-21 CI repair

- Baseline: all original 32 tests passed in WSL Ubuntu 24.04.
- Regression before implementation: the no-HNAT C fixture failed on the seven
  identifiers reported by CI; the installer tests failed because preparation
  did not install a compatibility patch; the configuration gate accepted all
  seven unwanted bootloader packages.
- Initial fix suite: **40 tests passed, no skips**, with Python 3.12.3 and Clang 18.1.3.
- HNAT disabled: patched fixture compiles and runs, preserving ordinary receive
  and reset behavior without HNAT notifications or waits.
- HNAT built in and as a module: preprocessed nonblank code is identical before
  and after the patch; both compile and run their expected behavior.
- The full Ethernet driver was reconstructed from Linux 6.6.133 and the locked
  upstream patch stack. All seven original diagnostic line numbers matched CI.
  The new patch applies with GNU patch `--dry-run --fuzz=0`, without offsets.
- The real `prepare` command passed on a separate sparse checkout of locked
  source `ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8`, using the existing public
  key and `linux-original-474m`. The installed patch, archived copy and SHA256
  report agree.
- Python compilation, Bash/POSIX shell syntax and both workflow YAML parses
  passed. The recipe checksum list was regenerated for the changed/new files.

The tests use verbatim affected driver regions with minimal kernel interface
stubs. They do not constitute a complete Linux driver cross-build. No full
OpenWrt `make defconfig`, firmware compilation, image packaging or hardware
boot/flash test was performed locally. A new CI run is required to verify the
complete firmware build from the corrected revision.

## First remote verification and follow-up

Run 35553289535 used commit `141f2c6`. All 40 tests passed with the GitHub
runner's compiler, and preparation installed the kernel patch. `make defconfig`
still enabled the hidden N60 Pro U-Boot package and its NAND ATF dependency;
the strengthened configuration gate correctly stopped before download/compile.

The actual upstream U-Boot package has `HIDDEN:=1` and a device-based default y.
A Kconfig experiment reproduced explicit user n being ignored for this hidden
symbol and the ATF dependency being selected. Changing the package default to n
disabled both. The follow-up changes only the N60 Pro U-Boot variant's default
in source preparation, with GNU make regression tests evaluating the result.

After the hidden-default follow-up: **43 tests passed, no skips**. The real
`prepare` command also passed on another fresh copy of the locked source.
