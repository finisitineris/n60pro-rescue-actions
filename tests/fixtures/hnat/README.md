# HNAT compatibility C regression fixture

`mtk_eth_soc.c` is a reduced fixture, not a replacement Ethernet driver. Its
relevant regions are copied verbatim from the fully patched Linux 6.6.133
MediaTek driver at:

- Repository: `padavanonly/immortalwrt-mt798x-6.6`
- Commit: `ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8`
- Kernel base: `gregkh/linux` tag `v6.6.133`,
  `drivers/net/ethernet/mediatek/mtk_eth_soc.c`
- Kernel base SHA256: `fea18f2037f5efe5e7e752a41fc02bc03cb273947d600ffa32febde41d05f745`
- Fully patched driver SHA256 (LF): `edbd4e6d54d66351f1278dc7c90b5744fdc9d71c7aa4a081fc69d3dd0180cdc7`

Reconstruction applies the driver sections from all 54 relevant patches, in
sorted order within generic/backport-6.6, generic/pending-6.6,
generic/hack-6.6, then mediatek/patches-6.6. The existing upstream patches need
normal GNU patch fuzz in a few places. The new compatibility patch applies
to that reconstructed driver with `--fuzz=0`, without offsets. The unguarded
symbol locations match the observed CI errors exactly: 2510, 5492, 5538,
5540, 7190, 7197, 7201.

The copied source ranges are 39-51 (declarations), 2505-2520 (RX),
5483-5502 (reset start), 5532-5545 (reset completion), and 7186-7214 (notifier).
The surrounding reduced functions and `main` are test scaffolding.
`kernel_stubs.h` supplies only unrelated kernel infrastructure.
`mtk_hnat/nf_hnat_mtk.h` contains the seven real, verbatim upstream symbol
definitions; it remains included only for HNAT=y/m. No test definitions are
installed by the production patch.

Upstream dependencies whose SHA256 values anchor the installer:

| Path beneath `target/linux/mediatek` | SHA256 |
| --- | --- |
| `patches-6.6/9999-01-hnat.patch` | `21e74e4a3bee83f9a608240299782efe6d561b0cb1ddba38d4e3a404e84c0782` |
| `patches-6.6/9999-02-mtk_enhance.patch` | `0a94b89507477186142ede359f9105f3ea41f8d9c28a1bf68046679c26689337` |
| `files-6.6/drivers/net/ethernet/mediatek/mtk_hnat/nf_hnat_mtk.h` | `598e12ff7d48c1cb3198cc3ec310ca808825b6c23a432a4953fe36e8b6a98a42` |

The regression tests apply the delivered patch using GNU patch with zero
fuzz, compile with a host C compiler and warnings as errors, and execute the
fixture for HNAT=n/y/m. The unpatched n fixture must diagnose all seven missing
symbols. The patched n fixture must preserve normal RX/reset operations while
skipping HNAT remapping, notifications and waits. Enabled variants must retain
identical preprocessed nonblank lines and execute the original HNAT behavior.
Clang retains different blank lines around added preprocessor directives;
only empty lines are ignored in the comparison.

This is an offline host regression and genuine upstream patch-application
check. It does not claim a complete kernel cross-build or hardware validation.
