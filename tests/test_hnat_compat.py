"""Compile the real patch against verbatim upstream regions, with kernel stubs.

These are host C regressions, not a complete driver or firmware cross-build.
Removing a guard breaks HNAT=n; excluding any enabled statement changes the
preprocessed y/m output or the observed receive/reset/notifier behavior.
"""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
FIXTURE = BASE / 'tests/fixtures/hnat'
PATCH = BASE / 'patches/9999-99-n60pro-rescue-no-hnat.patch'
DRIVER = Path('drivers/net/ethernet/mediatek/mtk_eth_soc.c')


class HnatCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = shlex.split(os.environ.get('CC', 'cc'))
        if not shutil.which(cls.cc[0]) or not shutil.which('patch'):
            raise unittest.SkipTest('host C compiler and GNU patch required (CI installs both)')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = self.root / 'original' / DRIVER
        self.patched = self.root / 'patched' / DRIVER
        for target in (self.original, self.patched):
            shutil.copytree(FIXTURE, target.parent)
        self.assertTrue(PATCH.is_file(), 'The kernel compatibility patch must be delivered')
        result = subprocess.run(
            ['patch', '--batch', '--fuzz=0', '-p1', '-i', str(PATCH)],
            cwd=self.root / 'patched', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def compile(self, source, mode, preprocess=False):
        command = self.cc + ['-std=c11', '-Wall', '-Werror', '-Wno-unused-parameter']
        if mode == 'y':
            command += ['-DCONFIG_NET_MEDIATEK_HNAT=1']
        elif mode == 'm':
            command += ['-DCONFIG_NET_MEDIATEK_HNAT_MODULE=1']
        if preprocess:
            command += ['-E', '-P']
        else:
            command += ['-o', str(self.root / 'fixture')]
        return subprocess.run(command + [str(source)], capture_output=True, text=True)

    def test_unpatched_hnat_disabled_reproduces_all_reported_undefined_symbols(self):
        result = self.compile(self.original, 'n')
        self.assertNotEqual(result.returncode, 0)
        for symbol in ('HIT_BIND_FORCE_TO_CPU', 'MTK_FE_START_RESET',
                       'MTK_FE_RESET_NAT_DONE', 'MTK_FE_RESET_DONE',
                       'MTK_WIFI_RESET_DONE', 'MTK_WIFI_CHIP_ONLINE',
                       'MTK_WIFI_CHIP_OFFLINE'):
            self.assertIn(symbol, result.stderr)

    def test_hnat_disabled_compiles_and_keeps_normal_ethernet_behavior(self):
        result = self.compile(self.patched, 'n')
        self.assertEqual(result.returncode, 0, result.stderr)
        run = subprocess.run([str(self.root / 'fixture')], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_builtin_and_module_keep_identical_preprocessed_behavior(self):
        for mode in ('y', 'm'):
            with self.subTest(mode=mode):
                original = self.compile(self.original, mode, preprocess=True)
                patched = self.compile(self.patched, mode, preprocess=True)
                self.assertEqual(original.returncode, 0, original.stderr)
                self.assertEqual(patched.returncode, 0, patched.stderr)
                # Clang retains different blank lines around added directives.
                self.assertEqual([line for line in patched.stdout.splitlines() if line.strip()],
                                 [line for line in original.stdout.splitlines() if line.strip()])
                result = self.compile(self.patched, mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                run = subprocess.run([str(self.root / 'fixture')], capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == '__main__':
    unittest.main()
