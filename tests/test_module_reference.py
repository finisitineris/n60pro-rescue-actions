"""A module-only build must not silently change the running kernel's recipe."""
import importlib.util
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('module_reference', BASE / 'scripts/module_reference.py')
REF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REF)


class ConfigurationDeltaTests(unittest.TestCase):
    BEFORE = 'CONFIG_TARGET_mediatek=y\nCONFIG_KERNEL_PRINTK=y\n# CONFIG_PACKAGE_kmod-mtd-rw is not set\n'

    def test_accepts_only_external_module_selection(self):
        after = self.BEFORE.replace('# CONFIG_PACKAGE_kmod-mtd-rw is not set', 'CONFIG_PACKAGE_kmod-mtd-rw=m')
        REF.check_config_delta(self.BEFORE, after)

    def test_rejects_kernel_change(self):
        after = self.BEFORE.replace('# CONFIG_PACKAGE_kmod-mtd-rw is not set', 'CONFIG_PACKAGE_kmod-mtd-rw=m')
        after = after.replace('CONFIG_KERNEL_PRINTK=y', '# CONFIG_KERNEL_PRINTK is not set')
        with self.assertRaisesRegex(ValueError, 'CONFIG_KERNEL_PRINTK'):
            REF.check_config_delta(self.BEFORE, after)

    def test_rejects_module_installed_into_image(self):
        after = self.BEFORE.replace('# CONFIG_PACKAGE_kmod-mtd-rw is not set', 'CONFIG_PACKAGE_kmod-mtd-rw=y')
        with self.assertRaisesRegex(ValueError, 'module-only'):
            REF.check_config_delta(self.BEFORE, after)

    def test_rejects_extra_package_or_missing_option(self):
        after = self.BEFORE.replace('# CONFIG_PACKAGE_kmod-mtd-rw is not set', 'CONFIG_PACKAGE_kmod-mtd-rw=m')
        for changed in [after + 'CONFIG_PACKAGE_dockerd=y\n', after.replace('CONFIG_TARGET_mediatek=y\n', '')]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                REF.check_config_delta(self.BEFORE, changed)

    def test_rejects_duplicate_config_key(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            REF.config_values('CONFIG_A=y\nCONFIG_A=n\n')

    def test_comments_order_and_disabled_style_are_not_kernel_changes(self):
        REF.check_config_delta(self.BEFORE,
            '# generated comment\nCONFIG_PACKAGE_kmod-mtd-rw=m\nCONFIG_KERNEL_PRINTK=y\nCONFIG_TARGET_mediatek=y\n')


if __name__ == '__main__':
    unittest.main()
