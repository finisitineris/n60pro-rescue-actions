"""N60 Pro U-Boot default-selection regressions using real GNU Make."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rescue_bootloader_test', BASE / 'scripts/rescue.py')
RESCUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESCUE)

RECIPE = '''define U-Boot/Default
  BUILD_TARGET:=mediatek
  UBOOT_IMAGE:=u-boot-mtk.bin
  HIDDEN:=1
endef

define U-Boot/mt7986_netcore_n60
  NAME:=Netcore N60
  BUILD_SUBTARGET:=filogic
  BUILD_DEVICES:=netcore_n60
  UBOOT_CONFIG:=mt7986_netcore_n60
  UBOOT_IMAGE:=u-boot.fip
  BL2_BOOTDEV:=spim-nand
  BL2_SOC:=mt7986
  BL2_DDRTYPE:=ddr3
  DEPENDS:=+trusted-firmware-a-mt7986-spim-nand-ddr3
endef

define U-Boot/mt7986_netcore_n60-pro
  NAME:=Netcore N60 Pro
  BUILD_SUBTARGET:=filogic
  BUILD_DEVICES:=netcore_n60-pro
  UBOOT_CONFIG:=mt7986_netcore_n60-pro
  UBOOT_IMAGE:=u-boot.fip
  BL2_BOOTDEV:=spim-nand
  BL2_SOC:=mt7986
  BL2_DDRTYPE:=ddr4
  DEPENDS:=+trusted-firmware-a-mt7986-spim-nand-ddr4
endef
'''

HARNESS = r'''
define U-Boot/Init
  BUILD_TARGET:=
  BUILD_SUBTARGET:=
  BUILD_DEVICES:=
  NAME:=
  DEPENDS:=
  HIDDEN:=
  DEFAULT:=
  VARIANT:=$(1)
  UBOOT_CONFIG:=$(1)
  UBOOT_IMAGE:=u-boot.bin
endef

define Capture
  $(eval $(call U-Boot/Init,$(1)))
  $(eval $(call U-Boot/Default,$(1)))
  $(eval $(call U-Boot/$(1),$(1)))
  $(info RESULT|$(1)|$(DEFAULT)|$(BUILD_DEVICES)|$(DEPENDS)|$(HIDDEN)|$(UBOOT_CONFIG)|$(BL2_DDRTYPE))
endef

$(eval $(call Capture,mt7986_netcore_n60-pro))
$(eval $(call Capture,mt7986_netcore_n60))

.PHONY: all
all:
	@:
'''


def transform(text):
    return RESCUE.disable_n60pro_uboot_default(text)


@unittest.skipUnless(shutil.which('make'), 'needs GNU make')
class BootloaderDefaultTests(unittest.TestCase):
    def evaluate(self, recipe):
        with tempfile.TemporaryDirectory(prefix='n60-uboot-default-') as temp:
            makefile = Path(temp) / 'Makefile'
            makefile.write_text(recipe + HARNESS, encoding='utf-8')
            result = subprocess.run(['make', '--no-print-directory', '-f', str(makefile)],
                                    text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [line for line in result.stdout.splitlines() if line.startswith('RESULT|')]

    def test_selected_variant_evaluates_default_n_without_changing_recipe_fields(self):
        self.assertEqual(self.evaluate(transform(RECIPE)), [
            'RESULT|mt7986_netcore_n60-pro|n|netcore_n60-pro|'
            '+trusted-firmware-a-mt7986-spim-nand-ddr4|1|mt7986_netcore_n60-pro|ddr4',
            'RESULT|mt7986_netcore_n60||netcore_n60|'
            '+trusted-firmware-a-mt7986-spim-nand-ddr3|1|mt7986_netcore_n60|ddr3',
        ])

    def test_missing_or_duplicate_selected_variant_is_rejected(self):
        block = RECIPE[RECIPE.index('define U-Boot/mt7986_netcore_n60-pro'):]
        for text in (RECIPE.replace(block, ''), RECIPE + '\n' + block):
            with self.subTest(size=len(text)):
                with self.assertRaisesRegex(ValueError, 'N60 Pro U-Boot variant'):
                    transform(text)

    def test_wrong_selected_variant_baseline_is_rejected(self):
        changes = (
            ('  BL2_DDRTYPE:=ddr4\n', '  BL2_DDRTYPE:=ddr3\n'),
            ('  BUILD_DEVICES:=netcore_n60-pro\n', '  BUILD_DEVICES:=other\n'),
            ('  DEPENDS:=+trusted-firmware-a-mt7986-spim-nand-ddr4\n',
             '  DEPENDS:=+trusted-firmware-a-mt7986-spim-nand-ddr3\n'),
            ('  UBOOT_CONFIG:=mt7986_netcore_n60-pro\n', '  DEFAULT:=y\n'),
        )
        for old, new in changes:
            with self.subTest(replacement=new.strip()):
                with self.assertRaisesRegex(ValueError, 'N60 Pro U-Boot baseline'):
                    transform(RECIPE.replace(old, new))


if __name__ == '__main__':
    unittest.main()
