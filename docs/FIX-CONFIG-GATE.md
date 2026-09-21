# Configuration gate fix — 2026-09-21

Base recipe: `fc785f88b9d294fde2dece01cbe0065ba6a8b269`.

## Scope

Fix the false rejection of
`CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Haproxy=y` as a selected package.
Real package identities now come from `tmp/.packageinfo` top-level `Package:`
records. Description/Config multiline blocks are skipped through their `@@`
terminators. Missing, unreadable, empty, malformed or obviously incomplete
metadata fails closed. Existing forbidden-package and required-symbol rules
are unchanged; no special exemption for Haproxy, LuCI or any name suffix.

`build.sh` now copies `.config` to `expanded.config` and `.packageinfo` to
`packageinfo.txt` BEFORE `configuration-check`. Both destination names already
match the existing diagnostics upload glob, so no workflow change is required.

## Verification

- Original 17 offline tests: PASS before the change.
- New regression tests reproduced the old false rejection and missing diagnostics.
- Complete suite after the fix: 32 tests, all PASS (Python unittest discovery).
- Python syntax checks and existing Bash/POSIX shell checks: PASS.
- A shell integration test executes the real build.sh with stubbed external
  phases. It forces configuration-check to exit 23, verifies both diagnostics
  survive, and verifies download/compile are never invoked after that failure.
- No full OpenWrt `make defconfig` or cross-compile was run in this environment.
- No firmware was flashed and no router was contacted.

Passing these tests fixes the reproduced configuration-gate bug; it does not
certify a full firmware build or hardware compatibility. A genuinely selected
forbidden package will still stop the next run, with diagnostics available.

## Use the corrected recipe

Merge the repair pull request, or apply the supplied patch to the same baseline.
Start a NEW `Build N60 Pro rescue` workflow run on the updated branch. Do not use
`Re-run jobs` on the old failed run: GitHub retains that run's original commit.
Keep the same source lock, layout and SSH public key. No cache purge is required
by this change. Complete firmware compilation remains manually triggered.
