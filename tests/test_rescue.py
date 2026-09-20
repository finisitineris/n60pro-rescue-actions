"""Offline tests: no network, cross compiler, firmware execution or router access."""
import base64
import hashlib
import importlib.util
import io
import json
import lzma
import struct
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

def make_fdt(nodes):
    strings = bytearray(); names = {}
    def nameoff(s):
        if s not in names:
            names[s] = len(strings); strings.extend(s.encode()+b'\0')
        return names[s]
    def pad(b): return b+b'\0'*((-len(b))%4)
    def node(name, props, children):
        out = struct.pack('>I',1)+pad(name.encode()+b'\0')
        for k,v in props.items():
            out += struct.pack('>III',3,len(v),nameoff(k))+pad(v)
        for child in children: out += node(*child)
        return out+struct.pack('>I',2)
    st = node('',{},nodes)+struct.pack('>I',9)
    off=56; total=off+len(st)+len(strings)
    return struct.pack('>10I',0xd00dfeed,total,off,off+len(st),40,17,16,0,len(strings),len(st))+bytes(16)+st+strings

def newc(entries):
    out=bytearray()
    for i,(name,data,mode) in enumerate(entries+[('TRAILER!!!',b'',0)]):
        nb=name.encode()+b'\0'; fields=[i,mode,0,0,1,0,len(data),0,0,0,0,len(nb),0]
        out += b'070701'+b''.join(f'{n:08x}'.encode() for n in fields)+nb
        out += b'\0'*((-len(out))%4); out += data; out += b'\0'*((-len(out))%4)
    return bytes(out)

class RescueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module_path=BASE/'scripts/rescue.py'
    def api(self):
        self.assertTrue(self.module_path.is_file(), 'Implementation scripts/rescue.py is not present yet')
        spec=importlib.util.spec_from_file_location('rescue',self.module_path)
        mod=importlib.util.module_from_spec(spec); sys.modules['rescue']=mod; spec.loader.exec_module(mod)
        return mod
    def test_parse_fdt(self):
        m=self.api(); b=make_fdt([('a',{'x':b'value\0'},[])])
        self.assertEqual(m.parse_fdt(b)['/a']['x'],b'value\0')
    def test_fdt_truncated_rejected(self):
        m=self.api(); b=make_fdt([('a',{'x':b'value\0'},[])])
        with self.assertRaises(ValueError): m.parse_fdt(b[:-2])
    def test_duplicate_property_rejected(self):
        m=self.api(); b=bytearray(make_fdt([('a',{'x':b'A\0','y':b'B\0'},[])]))
        pos=b.find(struct.pack('>I',3),68); pos2=b.find(struct.pack('>I',3),pos+4)
        b[pos2+8:pos2+12]=b[pos+8:pos+12]
        with self.assertRaises(ValueError): m.parse_fdt(bytes(b))
    def test_public_key_only(self):
        m=self.api(); key=b'\0\0\0\x0bssh-ed25519'+b'\0\0\0\x20'+bytes(range(32))
        valid='ssh-ed25519 '+base64.b64encode(key).decode()+' test'
        self.assertTrue(m.validate_key(valid).startswith('ssh-ed25519 '))
        for bad in ['-----BEGIN OPENSSH PRIVATE KEY-----',valid+'\n'+valid,'command="rm /" '+valid]:
            with self.subTest(bad=bad[:30]), self.assertRaises(ValueError): m.validate_key(bad)
    def test_cpio_valid(self):
        m=self.api(); files=m.read_cpio(newc([('init',b'abc',0o100755),('sbin/init',b'/sbin/procd',0o120777)]))
        self.assertEqual(files['init'][1],b'abc')
    def test_cpio_traversal(self):
        m=self.api()
        with self.assertRaises(ValueError): m.read_cpio(newc([('../etc/passwd',b'x',0o100644)]))
    def test_cpio_truncated(self):
        m=self.api()
        with self.assertRaises(ValueError): m.read_cpio(newc([('init',b'abc',0o100755)])[:115])
    def test_cpio_dot_root(self):
        m=self.api(); self.assertIn('init',m.read_cpio(newc([('.',b'',0o40755),('./init',b'x',0o100755)])))
    def test_decompression_limit(self):
        m=self.api(); b=lzma.compress(b'a'*10000)
        with self.assertRaises(ValueError): m.unpack(b,limit=100)
    def test_decompression(self):
        m=self.api(); self.assertEqual(m.unpack(lzma.compress(b'abc'),limit=100),b'abc')
    def test_tar_roundtrip(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.bin'; m.write_bridge(p,b'FIT',b'ROOT',123)
            self.assertEqual(m.read_sysupgrade(p), (b'FIT',b'ROOT'))
            with tarfile.open(p) as tf: self.assertEqual(len(tf.getmembers()),4)
    def test_tar_extra_rejected(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.tar'
            with tarfile.open(p,'w',format=tarfile.USTAR_FORMAT) as t:
                for n in ['kernel','root','fip']:
                    i=tarfile.TarInfo('sysupgrade-netcore_n60-pro/'+n); i.size=1; t.addfile(i,io.BytesIO(b'x'))
            with self.assertRaises(ValueError): m.read_sysupgrade(p)
    def test_dts_patch_two_layouts(self):
        m=self.api()
        original='''/dts-v1/; / { compatible = "netcore,n60-pro", "mediatek,mt7986a"; memory@40000000 { reg = <0 0x40000000 0 0x20000000>; }; };\n&spi0 { flash@0 { mediatek,nmbm; partitions { partition@0 { label = "bl2"; reg = <0x0 0x100000>; read-only; }; partition@100000 { label = "u-boot-env"; reg = <0x100000 0x80000>; }; partition@180000 { label = "factory"; reg = <0x180000 0x200000>; nvmem-layout { foo { x = <1>; }; }; }; partition@380000 { label = "fip"; reg = <0x380000 0x200000>; read-only; }; partition@580000 { label = "ubi"; reg = <0x0580000 0x7280000>; }; }; }; };'''
        for layout in m.LAYOUTS:
            text=m.patch_dts(original,layout)
            self.assertIn(f'0x{m.LAYOUTS[layout]:08x}',text)
            self.assertEqual(text.count('read-only;'),4)
            self.assertIn('0x20000000',text)
            with self.assertRaises(ValueError): m.patch_dts(text,layout)
    def test_unknown_layout_rejected(self):
        m=self.api()
        with self.assertRaises(ValueError): m.patch_dts('', '506m')
    def test_parent_default_packages_are_pruned(self):
        m=self.api()
        self.assertTrue(hasattr(m,'prune_parent_defaults'),'Parent target defaults pruning is missing')
        original = 'KERNEL_PATCHVER:=6.6\ninclude $(INCLUDE_DIR)/target.mk\nDEFAULT_PACKAGES += \\\n\tautocore-arm kmod-fs-btrfs luci-app-ttyd \\\n\tautomount usbutils\n\n$(eval $(call BuildTarget))'
        actual=m.prune_parent_defaults(original)
        self.assertNotIn('luci-app-ttyd',actual)
        self.assertNotIn('automount',actual)
        self.assertIn('DEVICE_TYPE:=basic\ninclude',actual)
        self.assertIn('usbutils',actual)
        with self.assertRaises(ValueError): m.prune_parent_defaults('unrelated target')

    def test_kernel_variants_may_differ(self):
        m=self.api()
        a={'kernel':({'description':b'ARM64 Linux-6.6.133\0'},b'kernel-with-initrd'), 'fdt':({},b'dtb')}
        b={'kernel':({'description':b'ARM64 Linux-6.6.133\0'},b'normal-kernel'), 'fdt':({},b'dtb')}
        self.assertFalse(m.compare_variants(a,b))
        b['kernel'][0]['description']=b'ARM64 Linux-5.4\0'
        with self.assertRaises(ValueError): m.compare_variants(a,b)

    def test_validate_sha_child(self):
        m=self.api(); data=b'hello'; tree={'/images/k':{'data':data},'/images/k/hash-1':{'algo':b'sha1\0','value':hashlib.sha1(data).digest()}}
        m.verify_hashes(tree,'/images/k',data)
        with self.assertRaises(ValueError): m.verify_hashes(tree,'/images/k',b'broken')

if __name__=='__main__': unittest.main()
