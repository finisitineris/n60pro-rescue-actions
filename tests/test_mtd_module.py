"""Offline artifact-gate tests; fixtures are real tar/gzip and ELF structures."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
KERNEL_DEP = '6.6.133~030ad1570833e99b365a217a0ba91204-r1'
VERMAGIC = '6.6.133 SMP mod_unload aarch64 '
POSTINST = b'''#!/bin/sh
[ "${IPKG_NO_SCRIPT}" = "1" ] && exit 0
[ -s ${IPKG_INSTROOT}/lib/functions.sh ] || exit 0
. ${IPKG_INSTROOT}/lib/functions.sh
default_postinst $0 $@
'''
PRERM = b'''#!/bin/sh
[ -s ${IPKG_INSTROOT}/lib/functions.sh ] || exit 0
. ${IPKG_INSTROOT}/lib/functions.sh
default_prerm $0 $@
'''


def elf(vermagic=VERMAGIC, machine=183, imports=('get_mtd_device',), weak=(), name='mtd_rw'):
    """Small ELF64 ET_REL with a genuine section/symbol table, no executable code."""
    names = b'\0.shstrtab\0.modinfo\0.strtab\0.symtab\0'
    modinfo = f'vermagic={vermagic}\0name={name}\0license=GPL\0depends=\0'.encode()
    strings = b'\0'
    symbols = bytes(24)
    for symbol, binding in [(s, 1) for s in imports] + [(s, 2) for s in weak]:
        symbols += struct.pack('<IBBHQQ', len(strings), binding << 4, 0, 0, 0, 0)
        strings += symbol.encode() + b'\0'
    data = bytearray(bytes(64))
    sections = [bytes(64)]
    for section_name, body, kind, link, entrysize in [
        (b'.shstrtab', names, 3, 0, 0), (b'.modinfo', modinfo, 1, 0, 0),
        (b'.strtab', strings, 3, 0, 0), (b'.symtab', symbols, 2, 3, 24),
    ]:
        offset = len(data)
        data.extend(body)
        sections.append(struct.pack('<IIQQQQIIQQ', names.index(section_name), kind,
                                    0, 0, offset, len(body), link, 0, 1, entrysize))
    shoff = len(data)
    data.extend(b''.join(sections))
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    data[:64] = struct.pack('<16sHHIQQQIHHHHHH', ident, 1, machine, 1, 0, 0,
                           shoff, 0, 64, 0, 0, 64, len(sections), 1)
    return bytes(data)


def tar_gz(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz', format=tarfile.GNU_FORMAT) as archive:
        for name, content, kind in entries:
            item = tarfile.TarInfo(name)
            item.mode = 0o755 if kind == 'dir' else 0o644
            if kind == 'dir':
                item.type = tarfile.DIRTYPE
                archive.addfile(item)
            elif kind == 'link':
                item.type = tarfile.SYMTYPE
                item.linkname = content.decode()
                archive.addfile(item)
            else:
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
    return output.getvalue()


def ipk_bytes(module=None, dependency=KERNEL_DEP, arch='aarch64_cortex-a53',
              package='kmod-mtd-rw', extra_data=(), extra_control=(), data_entries=None,
              postinst=POSTINST):
    control = (f'Package: {package}\nVersion: 6.6.133.2021.02.28-r1\n'
               f'Depends: kernel (= {dependency})\nArchitecture: {arch}\n'
               'Description: MTD write support\n').encode()
    controls = [('./', b'', 'dir'), ('./control', control, 'file'),
                ('./postinst', postinst, 'file'), ('./prerm', PRERM, 'file'), *extra_control]
    entries = data_entries if data_entries is not None else [
        ('./', b'', 'dir'), ('./lib', b'', 'dir'), ('./lib/modules', b'', 'dir'),
        ('./lib/modules/6.6.133', b'', 'dir'),
        ('./lib/modules/6.6.133/mtd-rw.ko', module if module is not None else elf(), 'file'),
        *extra_data,
    ]
    return tar_gz([('./debian-binary', b'2.0\n', 'file'),
                   ('./control.tar.gz', tar_gz(controls), 'file'),
                   ('./data.tar.gz', tar_gz(entries), 'file')])


class MtdModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ipk = self.root / 'kmod-mtd-rw.ipk'
        self.ipk.write_bytes(ipk_bytes())
        self.reference = self.root / 'reference.ko'
        self.reference.write_bytes(elf(name='mtd'))
        self.kernel = self.root / 'linux-6.6.133'
        (self.kernel / 'include/config').mkdir(parents=True)
        (self.kernel / 'include/config/kernel.release').write_text('6.6.133\n')
        (self.kernel / '.vermagic').write_text('030ad1570833e99b365a217a0ba91204\n')
        (self.kernel / 'Module.symvers').write_text('0x00000000\tget_mtd_device\tvmlinux\tEXPORT_SYMBOL_GPL\t\n')
        self.out = self.root / 'validated'

    def api(self):
        path = BASE / 'scripts/validate_mtd_module.py'
        self.assertTrue(path.is_file(), 'Module artifact validator has not been implemented')
        spec = importlib.util.spec_from_file_location('validate_mtd_module', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def validate(self):
        return self.api().validate(self.ipk, self.reference, self.kernel, self.out)

    def rejected(self):
        with self.assertRaises(ValueError):
            self.validate()
        self.assertFalse(self.out.exists(), 'A rejected package must not publish deliverables')

    def test_matching_module_publishes_bytes_and_audit_without_runtime_claim(self):
        report = self.validate()
        self.assertEqual((self.out / self.ipk.name).read_bytes(), self.ipk.read_bytes())
        self.assertEqual((self.out / 'mtd-rw.ko').read_bytes(), elf())
        self.assertEqual(json.loads((self.out / 'validation.json').read_text()), report)
        self.assertEqual(report['kernel_dependency'], KERNEL_DEP)
        self.assertEqual(report['module']['vermagic'], VERMAGIC)
        self.assertEqual(report['module']['sha256'], hashlib.sha256(elf()).hexdigest())
        self.assertEqual(report['ipk']['sha256'], hashlib.sha256(self.ipk.read_bytes()).hexdigest())
        self.assertEqual(report['reference_module']['sha256'], hashlib.sha256(self.reference.read_bytes()).hexdigest())
        self.assertFalse(report['runtime_load_test_performed'])
        self.assertFalse(report['autoload_present'])
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ['kmod-mtd-rw.ipk', 'mtd-rw.ko', 'validation.json'])

    def test_exact_dependency_hash_is_required(self):
        self.ipk.write_bytes(ipk_bytes(dependency='6.6.133~130ad1570833e99b365a217a0ba91204-r1'))
        self.rejected()

    def test_dependency_must_be_equality_for_complete_kernel_version(self):
        for dependency in ['6.6.133', KERNEL_DEP + ' | kernel (= 6.6.133)', KERNEL_DEP + '), kernel (= 6.6.133']:
            with self.subTest(dependency=dependency):
                self.ipk.write_bytes(ipk_bytes(dependency=dependency))
                self.rejected()

    def test_wrong_package_identity_is_rejected(self):
        for kwargs in [{'package': 'kmod-other'}, {'arch': 'aarch64_generic'}]:
            with self.subTest(kwargs=kwargs):
                self.ipk.write_bytes(ipk_bytes(**kwargs))
                self.rejected()

    def test_vermagic_must_match_complete_trusted_reference(self):
        self.ipk.write_bytes(ipk_bytes(module=elf(vermagic='6.6.133 SMP aarch64 ')))
        self.rejected()

    def test_wrong_elf_architecture_is_rejected(self):
        self.ipk.write_bytes(ipk_bytes(module=elf(machine=62)))
        self.rejected()

    def test_elf_truncation_is_rejected(self):
        self.ipk.write_bytes(ipk_bytes(module=elf()[:-1]))
        self.rejected()

    def test_kernel_build_hash_is_independently_checked(self):
        (self.kernel / '.vermagic').write_text('wrong\n')
        self.rejected()

    def test_kernel_build_release_is_independently_checked(self):
        (self.kernel / 'include/config/kernel.release').write_text('6.6.133-custom\n')
        self.rejected()

    def test_undefined_strong_symbol_must_be_exported(self):
        self.ipk.write_bytes(ipk_bytes(module=elf(imports=('missing_mtd_api',))))
        self.rejected()

    def test_missing_weak_symbol_is_reported_but_allowed(self):
        self.ipk.write_bytes(ipk_bytes(module=elf(weak=('optional_api',))))
        report = self.validate()
        self.assertEqual(report['module']['undefined_weak_symbols'], ['optional_api'])
        self.assertEqual(report['module']['unresolved_weak_symbols'], ['optional_api'])

    def test_autoload_file_is_rejected(self):
        self.ipk.write_bytes(ipk_bytes(extra_data=[('./etc/modules.d/99-mtd-rw', b'mtd-rw i_want_a_brick=1\n', 'file')]))
        self.rejected()

    def test_other_modules_and_unrelated_payloads_are_rejected(self):
        for path in ['lib/modules/6.6.133/evil.ko', 'usr/bin/helper', 'etc/modules-boot.d/99-mtd-rw']:
            with self.subTest(path=path):
                self.ipk.write_bytes(ipk_bytes(extra_data=[(path, b'x', 'file')]))
                self.rejected()

    def test_archive_escape_names_are_rejected(self):
        for path in ['../escape', '/absolute', './lib/../../escape', 'C:/escape', 'lib\\escape']:
            with self.subTest(path=path):
                self.ipk.write_bytes(ipk_bytes(extra_data=[(path, b'x', 'file')]))
                self.rejected()

    def test_duplicate_normalized_archive_paths_are_rejected(self):
        self.ipk.write_bytes(ipk_bytes(extra_data=[('lib/modules/6.6.133/mtd-rw.ko', elf(), 'file')]))
        self.rejected()

    def test_symlink_payload_is_rejected(self):
        self.ipk.write_bytes(ipk_bytes(data_entries=[('lib/modules/6.6.133/mtd-rw.ko', b'/tmp/module', 'link')]))
        self.rejected()

    def test_maintainer_script_loading_module_is_rejected(self):
        self.ipk.write_bytes(ipk_bytes(extra_control=[('postinst-pkg', b'#!/bin/sh\ninsmod mtd-rw\n', 'file')]))
        self.rejected()

    def test_modified_stock_postinst_is_rejected(self):
        self.ipk.write_bytes(ipk_bytes(postinst=POSTINST + b'insmod mtd-rw\n'))
        self.rejected()

    def test_existing_output_is_preserved_and_rejected(self):
        self.out.mkdir()
        marker = self.out / 'keep'
        marker.write_text('keep')
        with self.assertRaises(ValueError):
            self.validate()
        self.assertEqual(marker.read_text(), 'keep')
        self.assertEqual(list(self.out.iterdir()), [marker])

    def test_cli_publishes_validated_artifact(self):
        self.api()
        result = subprocess.run([sys.executable, str(BASE / 'scripts/validate_mtd_module.py'),
                                 '--ipk', str(self.ipk), '--reference-module', str(self.reference),
                                 '--kernel-build', str(self.kernel), '--out', str(self.out)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.out / 'validation.json').is_file())


if __name__ == '__main__':
    unittest.main()
