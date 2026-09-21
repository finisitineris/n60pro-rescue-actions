#!/usr/bin/env python3
"""Recover pinned CI6 reference inputs and enforce a module-only config delta."""
import argparse
import hashlib
import json
from pathlib import Path
import re

FIT_NAME = 'n60pro-linux-original-474m-initramfs-kernel.bin'
FIT_SHA256 = '7b7d7077ecf2af188a326f892f44a97c3af0cad0697f1239942be4370031ef74'
CONFIG_SHA256 = 'd706c0cc881cb93251228e8e12b2237f68102aaa813d9c6e3065f350a6b9d480'
MODULE_OPTION = 'CONFIG_PACKAGE_kmod-mtd-rw'


def config_values(text):
    values = {}
    for line in text.splitlines():
        match = re.fullmatch(r'(CONFIG_[^=\s]+)=(.*)', line)
        disabled = re.fullmatch(r'# (CONFIG_\S+) is not set', line)
        if match:
            name, value = match.groups()
        elif disabled:
            name, value = disabled.group(1), 'n'
        else:
            continue
        if name in values:
            raise ValueError(f'Duplicate configuration option: {name}')
        values[name] = value
    return values


def check_config_delta(before, after):
    original, changed = config_values(before), config_values(after)
    if original.get(MODULE_OPTION) != 'n' or changed.get(MODULE_OPTION) != 'm':
        raise ValueError('Expected module-only selection: kmod-mtd-rw must change from n to m')
    differences = sorted(key for key in original.keys() | changed.keys()
                         if key != MODULE_OPTION and original.get(key) != changed.get(key))
    if differences:
        raise ValueError('Unexpected configuration changes: ' + ', '.join(differences))


def extract_reference(artifact_dir, out):
    # The source artifact is fixed to the successful build already booted by the user.
    from rescue import verify_fit, read_cpio, unpack
    fit = (artifact_dir / FIT_NAME).read_bytes()
    config = (artifact_dir / 'expanded.config').read_bytes()
    for label, data, digest in [('FIT', fit, FIT_SHA256), ('config', config, CONFIG_SHA256)]:
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'Original CI6 {label} SHA256 mismatch')
    image = verify_fit(fit, need_initrd=True)
    entries = read_cpio(unpack(image['ramdisk'][1]))
    modules = sorted(name for name in entries if name.startswith('lib/modules/6.6.133/') and name.endswith('.ko'))
    if not modules:
        raise ValueError('Original rescue initramfs has no 6.6.133 reference module')
    name = modules[0]
    mode, module = entries[name]
    if mode & 0o170000 != 0o100000:
        raise ValueError('Reference module is not a regular file')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'reference.config').write_bytes(config)
    (out / 'reference.ko').write_bytes(module)
    (out / 'reference.json').write_text(json.dumps({
        'run_id': 35557563714, 'artifact_id': 10622700119,
        'fit_sha256': FIT_SHA256, 'config_sha256': CONFIG_SHA256,
        'reference_module': name, 'module_sha256': hashlib.sha256(module).hexdigest(),
    }, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    extract = sub.add_parser('extract')
    extract.add_argument('--artifact-dir', type=Path, required=True)
    extract.add_argument('--out', type=Path, required=True)
    delta = sub.add_parser('check-config')
    delta.add_argument('--before', type=Path, required=True)
    delta.add_argument('--after', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'extract':
        extract_reference(args.artifact_dir, args.out)
    else:
        check_config_delta(args.before.read_text(encoding='utf-8'), args.after.read_text(encoding='utf-8'))
        print('Only kmod-mtd-rw=m differs from the original CI6 configuration.')


if __name__ == '__main__':
    main()
