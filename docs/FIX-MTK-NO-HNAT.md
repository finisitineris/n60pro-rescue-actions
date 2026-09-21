# MediaTek Ethernet without HNAT — 2026-09-21

Failed run: https://github.com/finisitineris/n60pro-rescue-actions/actions/runs/35547438888

Recipe baseline: `71e2b962f409ba67e8309990f3cf5e41950dbbc6`.
Source remains pinned to `ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8`.

## Cause

The configuration gate and download phases passed. Kernel compilation stopped in
`drivers/net/ethernet/mediatek/mtk_eth_soc.c` because seven identifiers were
undeclared: `HIT_BIND_FORCE_TO_CPU`, `MTK_FE_START_RESET`,
`MTK_FE_RESET_NAT_DONE`, `MTK_FE_RESET_DONE`, `MTK_WIFI_RESET_DONE`,
`MTK_WIFI_CHIP_ONLINE`, and `MTK_WIFI_CHIP_OFFLINE`.

The locked upstream `9999-01-hnat.patch` adds references outside HNAT guards,
while the header providing these identifiers is included only when
`CONFIG_NET_MEDIATEK_HNAT` or `CONFIG_NET_MEDIATEK_HNAT_MODULE` is defined.
The rescue configuration omits the optional HNAT/Wi-Fi packages.

## Fix

`patches/9999-99-n60pro-rescue-no-hnat.patch` is installed after the upstream
patches. It guards the HNAT-dependent receive and reset-notification code with
the same condition as the header. The normal Ethernet path and notifier object
remain available. No new numeric definitions are added to the driver.

`prepare` verifies the upstream HNAT/enhancement patches and header SHA256 values before installing
the fix. It saves the exact patch and `kernel-compatibility.json` in `dist/`;
both successful-candidate and failure-diagnostic artifacts include them.
Source/feed locks, NAND layout, DTS policy and image validation are unchanged.

The diagnostics also showed seven unwanted bootloader package defaults:
six `trusted-firmware-a-*` variants and `u-boot-mt7986_netcore_n60-pro`.
The recipe explicitly disables the visible ATF defaults and the configuration
gate recognizes their actual upstream prefixes. N60 Pro's U-Boot package is
hidden, so Kconfig ignores an explicit user `n` and restores its device-based
`default y`; it then selects the NAND ATF dependency. `prepare` therefore sets
`DEFAULT:=n` in that one upstream U-Boot variant before `make defconfig`.
Other device variants are unchanged. The allowed `uboot-envtools` utility
remains enabled. This enforces the existing rescue-only policy.

## PPE conntrack dependency found by full CI

Run 35554014759 passed the configuration gate and compiled `mtk_eth_soc.o`.
It then failed at six `ct->mark` accesses in `mtk_ppe_offload.c`. The vendor
QoS patch uses that field unconditionally, but the minimal kernel configuration
disabled `NF_CONNTRACK_MARK`.

The Filogic target already enables `NETFILTER` and `NF_CONNTRACK`. Preparation
now adds `NETFILTER_ADVANCED=y` and `NF_CONNTRACK_MARK=y` to its kernel config.
Both are necessary: the real Linux Kconfig makes MARK depend on ADVANCED.
This supplies the vendor driver's dependency without changing its queue-selection
code. It does not select the `kmod-nf-conntrack` package, its sysctl defaults, or
the unrelated conntrack-zones option. Existing source/feed and image policies
remain the same. Preparation rejects a changed target baseline before editing.

## Validation

The C regression fixture contains the affected upstream code and minimal host
interface stubs. Tests verify the original seven undeclared identifiers, syntax
compilation with HNAT disabled after patching, and unchanged preprocessed code
with HNAT built in or as a module. These tests are not a full driver cross-build.
Installer tests cover exact copying, hash reporting and rejection of missing or
modified upstream inputs, missing recipe patches and existing destination files.

Run the complete offline suite in Linux:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
bash -n scripts/build.sh
sh -n overlay/usr/sbin/rescue-report
sh -n overlay/etc/board.d/02_network
```

The C tests require `cc` and `patch`; these are present on the target GitHub
Ubuntu runner. Passing offline checks does not establish complete firmware
compilation or hardware boot compatibility.

## Build the corrected revision

Start a new `Build N60 Pro rescue` run on the branch containing the fix. Keep
`layout=linux-original-474m`, `build_jobs=2`, and the previously used SSH public
key. Re-running the failed run would build its original commit.

The prepare log should contain:

```text
Installed kernel compatibility patch: 9999-99-n60pro-rescue-no-hnat.patch
```

Kernel preparation must subsequently show that patch being applied. Complete
build success is established only when compilation, packaging and image
validation all finish successfully. No router or flash operation is part of
this repair.
