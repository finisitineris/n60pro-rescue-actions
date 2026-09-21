"""The pinned vendor PPE requires the conntrack mark field even without HNAT."""
import importlib.util
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rescue_kernel_dependencies', BASE / 'scripts/rescue.py')
RESCUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESCUE)


class KernelDependencyTests(unittest.TestCase):
    BASELINE = 'CONFIG_NETFILTER=y\nCONFIG_NET_MEDIATEK_SOC=y\nCONFIG_NF_CONNTRACK=y\nCONFIG_NF_FLOW_TABLE=y\n'

    def test_adds_only_the_required_mark_field(self):
        result = RESCUE.enable_ppe_conntrack_mark(self.BASELINE)
        self.assertEqual(result.count('CONFIG_NF_CONNTRACK_MARK=y\n'), 1)
        self.assertEqual(result.count('CONFIG_NETFILTER_ADVANCED=y\n'), 1)
        self.assertEqual(result.replace('CONFIG_NF_CONNTRACK_MARK=y\n', '')
                              .replace('CONFIG_NETFILTER_ADVANCED=y\n', ''), self.BASELINE)

    def test_rejects_changed_conntrack_baseline(self):
        for value in ('n', 'm'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'conntrack baseline'):
                RESCUE.enable_ppe_conntrack_mark(self.BASELINE.replace('CONFIG_NF_CONNTRACK=y',
                                                                      'CONFIG_NF_CONNTRACK=' + value))

    def test_rejects_existing_or_duplicate_mark_config(self):
        for line in ('CONFIG_NF_CONNTRACK_MARK=y\n', '# CONFIG_NF_CONNTRACK_MARK is not set\n',
                     'CONFIG_NETFILTER_ADVANCED=y\n', '# CONFIG_NETFILTER_ADVANCED is not set\n'):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, 'mark baseline'):
                RESCUE.enable_ppe_conntrack_mark(self.BASELINE + line)


if __name__ == '__main__':
    unittest.main()
