"""Configuration-gate regressions; no downloads, compiler or router access."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rescue_config_test', BASE / 'scripts/rescue.py')
RESCUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESCUE)

REQUIRED = (
    'TARGET_mediatek', 'TARGET_mediatek_filogic',
    'TARGET_mediatek_filogic_DEVICE_netcore_n60-pro',
    'TARGET_ROOTFS_INITRAMFS', 'TARGET_ROOTFS_INITRAMFS_SEPARATE',
    'TARGET_INITRAMFS_COMPRESSION_XZ', 'TARGET_ROOTFS_SQUASHFS',
    'PACKAGE_dropbear', 'PACKAGE_ubi-utils', 'PACKAGE_mtd', 'PACKAGE_dnsmasq',
)
PACKAGES = ('dropbear', 'ubi-utils', 'mtd', 'dnsmasq', 'libc', 'uboot-envtools',
            'luci-app-passwall', 'luci-app-ttyd', 'wpad-openssl', 'kmod-mt_wifi',
            'dockerd', 'default-settings', 'uboot-mediatek-n60pro',
            'arm-trusted-firmware-mt7986',
            'trusted-firmware-a-mt7981-ram-ddr3',
            'trusted-firmware-a-mt7981-ram-ddr4',
            'trusted-firmware-a-mt7986-ram-ddr3',
            'trusted-firmware-a-mt7986-ram-ddr4',
            'trusted-firmware-a-mt7986-spim-nand-ddr4',
            'trusted-firmware-a-mt7988-ram-comb',
            'u-boot-mt7986_netcore_n60-pro')


def config(extra=''):
    return ''.join(f'CONFIG_{symbol}=y\n' for symbol in REQUIRED) + extra


def metadata(names=PACKAGES):
    # Same top-level Package/Description/Config delimiters as package-dumpinfo.mk.
    return ''.join(f'Source-Makefile: package/{name}/Makefile\nPackage: {name}\n'
                   f'Title: {name}\nDescription: test package\n@@\n\n' for name in names)


class PackageConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.src = Path(self.temp.name)
        (self.src / 'tmp').mkdir()
        (self.src / '.config').write_text(config(), encoding='utf-8')
        self.info = self.src / 'tmp/.packageinfo'
        self.info.write_text(metadata(), encoding='utf-8')

    def assert_accepted(self):
        try:
            RESCUE.check_config(self.src)
        except (ValueError, OSError) as exc:
            self.fail(f'Valid configuration was rejected: {exc}')

    def test_minimal_real_packages_are_accepted(self):
        self.assert_accepted()

    def test_parent_disabled_feature_flags_do_not_select_a_package(self):
        (self.src / '.config').write_text(config(
            '# CONFIG_PACKAGE_luci-app-passwall is not set\n'
            'CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Haproxy=y\n'
            'CONFIG_PACKAGE_luci-app-passwall_INCLUDE_SingBox=y\n'
            'CONFIG_PACKAGE_luci-app-passwall_INCLUDE_Xray=y\n'), encoding='utf-8')
        self.assert_accepted()

    def test_real_forbidden_packages_remain_rejected(self):
        for name in PACKAGES[6:]:
            with self.subTest(package=name):
                (self.src / '.config').write_text(config(f'CONFIG_PACKAGE_{name}=y\n'), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Unexpected rescue package selected:'):
                    RESCUE.check_config(self.src)

    def test_real_package_named_like_feature_flag_is_not_exempted(self):
        name = 'luci-app-passwall_INCLUDE_Haproxy'
        self.info.write_text(metadata(PACKAGES + (name,)), encoding='utf-8')
        (self.src / '.config').write_text(config(f'CONFIG_PACKAGE_{name}=y\n'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Unexpected rescue package selected:'):
            RESCUE.check_config(self.src)

    def test_missing_metadata_fails_closed(self):
        self.info.unlink()
        with self.assertRaisesRegex(ValueError, '[Pp]ackage metadata'):
            RESCUE.check_config(self.src)

    def test_empty_or_non_metadata_text_fails_closed(self):
        for value in ('', 'not package metadata\n', 'Package: \n', 'Package: invalid/name\n'):
            with self.subTest(value=value):
                self.info.write_text(value, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, '[Pp]ackage metadata'):
                    RESCUE.check_config(self.src)

    def test_invalid_encoding_fails_closed(self):
        self.info.write_bytes(b'Package: dropbear\n\xff')
        with self.assertRaisesRegex(ValueError, '[Pp]ackage metadata'):
            RESCUE.check_config(self.src)

    def test_missing_required_package_record_fails_closed(self):
        self.info.write_text(metadata(tuple(n for n in PACKAGES if n != 'dropbear')), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '[Pp]ackage metadata'):
            RESCUE.check_config(self.src)

    def test_package_text_in_description_and_config_is_not_a_record(self):
        name = 'luci-app-passwall_INCLUDE_Haproxy'
        extra = f'Description: example text\nPackage: {name}\n@@\nConfig:\nPackage: {name}\n@@\n'
        self.info.write_text(metadata() + extra, encoding='utf-8')
        (self.src / '.config').write_text(config(f'CONFIG_PACKAGE_{name}=y\n'), encoding='utf-8')
        self.assert_accepted()

    def test_unterminated_metadata_block_fails_closed(self):
        self.info.write_text(metadata() + 'Config:\nbool "Incomplete"\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '[Pp]ackage metadata'):
            RESCUE.check_config(self.src)

    def test_duplicate_records_from_overrides_are_accepted(self):
        self.info.write_text(metadata() + metadata(('dropbear',)), encoding='utf-8')
        self.assert_accepted()

    def test_missing_required_kconfig_still_rejected(self):
        text = config().replace('CONFIG_PACKAGE_mtd=y\n', '# CONFIG_PACKAGE_mtd is not set\n')
        (self.src / '.config').write_text(text, encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Required Kconfig symbol not enabled: PACKAGE_mtd'):
            RESCUE.check_config(self.src)

    def test_second_device_still_rejected(self):
        (self.src / '.config').write_text(config('CONFIG_TARGET_mediatek_filogic_DEVICE_other=y\n'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'More than one target selected'):
            RESCUE.check_config(self.src)

    def test_missing_metadata_cli_is_nonzero(self):
        self.info.unlink()
        import sys
        result = subprocess.run([sys.executable, str(BASE / 'scripts/rescue.py'),
                                 'check-config', '--source', str(self.src)],
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('package metadata', result.stderr.lower())


class BuildDiagnosticsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('bash') and shutil.which('timeout'), 'needs bash and timeout')
    def test_diagnostics_survive_configuration_check_failure(self):
        # Exercise the real build.sh ordering with stubbed external phases.
        # The checker deliberately exits 23; no downloads/compilation can occur.
        with tempfile.TemporaryDirectory(prefix='n60-gate-test-') as temp:
            root = Path(temp)
            src, out, tools = root / 'source', root / 'dist', root / 'tools'
            (src / 'scripts').mkdir(parents=True)
            (src / 'tmp').mkdir()
            tools.mkdir()
            (src / '.config').write_text(config(), encoding='utf-8')
            (src / 'tmp/.packageinfo').write_text(metadata(), encoding='utf-8')
            calls = root / 'calls.txt'
            stubs = {
                'id': '#!/bin/sh\necho 1000\n',
                'git': '#!/bin/sh\necho 1750000000\n',
                'make': '#!/bin/sh\necho "make $*" >> "$CALL_LOG"\nexit 0\n',
                'python3': '#!/bin/sh\necho "python3 $*" >> "$CALL_LOG"\n'
                           'if [ "$2" = check-config ]; then echo "injected rejection" >&2; exit 23; fi\n',
            }
            for name, content in stubs.items():
                p = tools / name
                p.write_text(content, encoding='utf-8')
                p.chmod(0o755)
            feeds = src / 'scripts/feeds'
            feeds.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
            feeds.chmod(0o755)
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                       CALL_LOG=str(calls), BUILD_JOBS='2')
            result = subprocess.run(['bash', str(BASE / 'scripts/build.sh'), str(src), str(out)],
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
            for name, original in [('expanded.config', src / '.config'),
                                   ('packageinfo.txt', src / 'tmp/.packageinfo')]:
                p = out / name
                self.assertTrue(p.is_file(), f'{name} lost when the checker failed')
                self.assertEqual(p.read_bytes(), original.read_bytes())
            self.assertIn('injected rejection', (out / 'logs/configuration-check.log').read_text())
            self.assertNotIn('make download', calls.read_text())
            self.assertNotIn('make -j', calls.read_text())


if __name__ == '__main__':
    unittest.main()
