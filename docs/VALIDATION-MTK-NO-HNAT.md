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
boot/flash test was performed locally. The remote results below establish the
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

## Full CI verification and PPE follow-up

Run 35554014759 used commit `1870739`. The configuration gate and download
passed. The HNAT patch applied cleanly, and `mtk_eth_soc.o` compiled without
the original seven errors. The next fatal error was six reads of `ct->mark`
in `mtk_ppe_offload.c` while the optional field was disabled.

The follow-up adds the kernel configuration dependencies `NETFILTER_ADVANCED=y`
and `NF_CONNTRACK_MARK=y` to the pinned Filogic target. No new package or PPE
driver patch is added. The dependency helper's tests failed before implementation;
the full suite now passes **46 tests, no skips**. Real source preparation passed
on another fresh checkout copy.

The actual locked `package-metadata.pl` and `kconfig.pl` scripts were replayed
against CI5 metadata and its expanded configuration. Both flags survive the
merge, and dependency evaluation of the original Linux 6.6.133 Netfilter Kconfig
confirms MARK is enabled only when ADVANCED is also enabled.

## Successful full firmware validation

[Run 35557563714](https://github.com/finisitineris/n60pro-rescue-actions/actions/runs/35557563714)
completed successfully in 1h 6m 29s using recipe commit
`84ffdf68cd8e0f083b3de3b421d97e586abc32c1` and the unchanged pinned source/feeds.
All 46 tests, the package configuration gate, firmware compilation, packaging
and offline image checks passed. Ethernet, PPE/offload and WED objects compiled
and the kernel linked successfully.

Downloaded artifacts were checked again locally:

- All 19 entries in the CI SHA256 manifest match, including the two diagnostic
  files supplied by the separate diagnostics artifact.
- Candidate size: 11,223,040 bytes; SHA256:
  `9f78482284b6744f0ac300843ba4219139adb211df2f21e7749b1aae9dd278f9`.
- Candidate FIT matches the standalone initramfs FIT; its root payload matches
  the ordinary same-build sysupgrade reference. FIT hashes and DTB checks pass.
- The compiled DTB retains UBI start `0x00580000`, size `0x1da80000` (474.5 MiB),
  and the protected BL2/environment/factory/FIP partitions.
- The embedded kernel configuration extracted from the ARM64 Image confirms
  `NETFILTER_ADVANCED=y`, `NF_CONNTRACK=y` and `NF_CONNTRACK_MARK=y`.
- The initrd contains 836 entries; CI verified all 571 regular rootfs files
  and equality of 23 module payloads between rootfs and initrd.
- Both actual package selection and the final package manifest exclude the
  forbidden Bootloader, HNAT/Wi-Fi, Docker and LuCI packages.

The successful artifact is an offline-validated rescue candidate. No router
was contacted, flashed or boot-tested. Later documentation-only commits do not
change the firmware's recorded recipe revision above.
