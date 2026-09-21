"""Exercise compatibility-patch installation without downloading kernel sources."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rescue_patch_install', BASE / 'scripts/rescue.py')
RESCUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESCUE)
NAME = '9999-99-n60pro-rescue-no-hnat.patch'
UPSTREAM = 'target/linux/mediatek/patches-6.6/9999-01-hnat.patch'


class KernelPatchInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.src, self.out, self.recipe = root / 'source', root / 'dist', root / 'recipe'
        self.upstream = self.src / UPSTREAM
        self.upstream.parent.mkdir(parents=True)
        self.upstream.write_bytes(b'locked upstream patch\n')
        self.out.mkdir()
        (self.recipe / 'patches').mkdir(parents=True)
        self.payload = b'--- a/driver.c\n+++ b/driver.c\n@@ -1 +1 @@\n-old\n+new\n'
        (self.recipe / 'patches' / NAME).write_bytes(self.payload)
        self.target = self.upstream.with_name(NAME)
        self.hashes = {UPSTREAM: hashlib.sha256(b'locked upstream patch\n').hexdigest()}
        self.addCleanup(patch.stopall)
        patch.object(RESCUE, 'BASE', self.recipe).start()
        patch.object(RESCUE, 'HNAT_BASELINE_HASHES', self.hashes, create=True).start()

    def install(self):
        self.assertTrue(hasattr(RESCUE, 'install_kernel_compat'),
                        'Build preparation does not install the HNAT compatibility patch')
        RESCUE.install_kernel_compat(self.src, self.out)

    def test_installs_exact_patch_and_saves_auditable_copy(self):
        self.install()
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual((self.out / NAME).read_bytes(), self.payload)
        report = json.loads((self.out / 'kernel-compatibility.json').read_text())
        self.assertEqual(report['patch'], NAME)
        self.assertEqual(report['sha256'], hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(report['upstream_sha256'], self.hashes)

    def test_modified_upstream_is_rejected_before_install(self):
        self.upstream.write_bytes(b'changed upstream patch\n')
        with self.assertRaisesRegex(ValueError, 'baseline'):
            self.install()
        self.assertFalse(self.target.exists())

    def test_missing_upstream_is_rejected_before_install(self):
        self.upstream.unlink()
        with self.assertRaisesRegex(ValueError, 'baseline'):
            self.install()
        self.assertFalse(self.target.exists())

    def test_missing_recipe_patch_is_rejected(self):
        (self.recipe / 'patches' / NAME).unlink()
        with self.assertRaisesRegex(ValueError, 'compatibility patch'):
            self.install()
        self.assertFalse(self.target.exists())

    def test_existing_patch_is_not_overwritten(self):
        self.target.write_bytes(b'local patch\n')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.install()
        self.assertEqual(self.target.read_bytes(), b'local patch\n')


if __name__ == '__main__':
    unittest.main()
