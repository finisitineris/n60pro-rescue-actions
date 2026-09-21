# N60 Pro rescue: matching mtd-rw module

This package is built for the already running CI6 rescue kernel only:

`6.6.133~030ad1570833e99b365a217a0ba91204-r1`

The build restores the original CI6 configuration and adds only
`CONFIG_PACKAGE_kmod-mtd-rw=m`. It checks the complete OpenWrt kernel ABI,
the package's exact kernel dependency and architecture, and the module's
ELF identity and vermagic against a module extracted from the original
SHA256-verified rescue initramfs. The source and feeds remain pinned.

The `.ipk` is the package; `mtd-rw.ko` is the same module extracted for
inspection. Neither file is a firmware or U-Boot image. Do not upload
either file to a firmware upgrade page. `validation.json` records the
checks performed. A successful build is not a runtime load test.

This delivery does not install or load the module, unlock partitions,
write flash, reboot, or alter the rescue image. It contains no autoload
configuration. Do not force dependency checks or replace kernel ABI
metadata. Software repository signature verification remains enabled.

Before any later use, verify this directory with `sha256sum -c SHA256SUMS`
and compare `opkg status kernel` on the router with the complete dependency
above. Stop on any mismatch. Installing a local package and loading its
module are separate operations; neither is performed by this build.

Bootloader compatibility remains a separate, unresolved check. The current
474.5 MiB UBI/NMBM layout differs from the proposed WildEdition defaults.
A validated module does not authorize or validate a bootloader write.
