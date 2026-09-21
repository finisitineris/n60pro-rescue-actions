#!/usr/bin/env python3
"""N60 Pro build preparation and OFFLINE image verification. Never contacts a router.

Only Python standard library is required; packaging also uses host unsquashfs/tar/dtc.
This is not a flash utility and does not establish hardware compatibility.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import zlib

LAYOUTS = {'linux-original-474m': 0x1DA80000, 'uboot-default-460m': 0x1CC00000}
BOARD = 'netcore,n60-pro'
TAR_BOARD = 'sysupgrade-netcore_n60-pro'
BASE = Path(__file__).resolve().parents[1]
PARTS = {'bl2':(0,0x100000), 'u-boot-env':(0x100000,0x80000),
         'factory':(0x180000,0x200000), 'fip':(0x380000,0x200000)}
HNAT_COMPAT_PATCH = '9999-99-n60pro-rescue-no-hnat.patch'
HNAT_BASELINE_HASHES = {
    'target/linux/mediatek/patches-6.6/9999-01-hnat.patch':
        '21e74e4a3bee83f9a608240299782efe6d561b0cb1ddba38d4e3a404e84c0782',
    'target/linux/mediatek/patches-6.6/9999-02-mtk_enhance.patch':
        '0a94b89507477186142ede359f9105f3ea41f8d9c28a1bf68046679c26689337',
    'target/linux/mediatek/files-6.6/drivers/net/ethernet/mediatek/mtk_hnat/nf_hnat_mtk.h':
        '598e12ff7d48c1cb3198cc3ec310ca808825b6c23a432a4953fe36e8b6a98a42',
}


def require(ok: bool, message: str) -> None:
    if not ok: raise ValueError(message)


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def validate_key(text: str) -> str:
    text = text.strip()
    require('\n' not in text and '\r' not in text and len(text) <= 8192, 'One public key line is required')
    parts = text.split()
    require(len(parts) >= 2 and parts[0] == 'ssh-ed25519', 'Supply an ssh-ed25519 PUBLIC key, not a private key or authorized_keys options')
    try: blob = base64.b64decode(parts[1], validate=True)
    except Exception as exc: raise ValueError('Invalid public key Base64') from exc
    require(len(blob) == 51 and blob[:19] == b'\0\0\0\x0bssh-ed25519\0\0\0\x20', 'Invalid Ed25519 public key structure')
    # Do not embed caller-controlled comments or shell syntax in generated scripts.
    return f'ssh-ed25519 {parts[1]} n60pro-rescue\n'


def patch_dts(text: str, layout: str) -> str:
    require(layout in LAYOUTS, 'Unknown layout; do not guess NAND geometry')
    require('"netcore,n60-pro"' in text and 'mediatek,nmbm;' in text, 'Source is not the expected N60 Pro NMBM DTS')
    # Pinned-source precondition: exactly one known UBI range, not arbitrary hex replacement.
    pattern = r'reg\s*=\s*<0x0?580000\s+0x0?7280000>\s*;'
    require(len(re.findall(pattern,text)) == 1, 'Unexpected DTS baseline/patch already applied')
    text = re.sub(pattern, f'reg = <0x00580000 0x{LAYOUTS[layout]:08x}>;', text, count=1)
    for label,(start,size) in PARTS.items():
        # Find direct properties before any children; factory contains a nested nvmem layout.
        pattern = rf'(label\s*=\s*"{re.escape(label)}";\s*reg\s*=\s*<([^>]+)>;)(\s*read-only;)?'
        found = list(re.finditer(pattern,text))
        require(len(found)==1, f'Missing/ambiguous partition {label}')
        m=found[0]; cells=[int(x,0) for x in m.group(2).split()]
        require(cells==[start,size], f'Unexpected offset/size for {label}')
        if not m.group(3): text=text[:m.end()]+ '\n\t\t\t\tread-only;' +text[m.end():]
    # DDR and NMBM reserve policy stay unchanged. Do not hardcode 2 GiB here.
    return text


def parse_fdt(blob: bytes) -> dict[str, dict[str, bytes]]:
    require(len(blob)>=40, 'Short FDT header')
    magic,total,off_st,off_str,off_rsv,ver,last,boot,len_str,len_st=struct.unpack_from('>10I',blob)
    require(magic==0xD00DFEED and ver>=17 and last<=17, 'Unsupported FDT')
    require(40<=total<=len(blob) and off_st>=40 and off_str>=40, 'Invalid FDT total/offsets')
    require(off_st+len_st<=total and off_str+len_str<=total, 'FDT block exceeds file')
    strings=blob[off_str:off_str+len_str]; pos=off_st; end=off_st+len_st; stack=[]; result={}
    def string_name(off):
        require(0<=off<len(strings),'Bad FDT string offset')
        stop=strings.find(b'\0',off); require(stop>=off,'Unterminated FDT string')
        return strings[off:stop].decode('ascii')
    while pos+4<=end:
        token=struct.unpack_from('>I',blob,pos)[0]; pos+=4
        if token==1:
            stop=blob.find(b'\0',pos,end); require(stop>=pos,'Unterminated node')
            name=blob[pos:stop].decode('ascii'); require('/' not in name,'Invalid node name')
            stack.append(name); path='/'.join(stack) or '/'
            require(path not in result,'Duplicate FDT node'); result[path]={}
            pos=(stop+4)&~3
        elif token==2:
            require(bool(stack),'Unbalanced FDT END_NODE'); stack.pop()
        elif token==3:
            require(bool(stack) and pos+8<=end,'Invalid FDT property')
            size,noff=struct.unpack_from('>II',blob,pos); pos+=8
            require(pos+size<=end,'Truncated FDT property')
            name=string_name(noff); path='/'.join(stack) or '/'
            require(name not in result[path],'Duplicate FDT property')
            result[path][name]=blob[pos:pos+size]; pos=(pos+size+3)&~3
        elif token==4: continue
        elif token==9:
            require(not stack and '/' in result,'Unbalanced/empty FDT'); return result
        else: raise ValueError(f'Unexpected FDT token {token}')
    raise ValueError('Missing FDT END token')


def cstr(value: bytes) -> str:
    require(value.endswith(b'\0'), 'String property is not NUL terminated')
    return value.rstrip(b'\0').decode('ascii')


def verify_hashes(tree, path, data):
    count=0
    for node,props in tree.items():
        if not node.startswith(path+'/hash') or node.count('/')!=path.count('/')+1: continue
        algo=cstr(props['algo'])
        if algo=='crc32': digest=struct.pack('>I',zlib.crc32(data)&0xffffffff)
        elif algo in ('sha1','sha256'): digest=hashlib.new(algo,data).digest()
        else: raise ValueError(f'Unexpected image hash algorithm: {algo}')
        require(digest==props.get('value'),f'{path}: {algo} mismatch'); count+=1
    require(count>0,f'{path}: no image hash was present')


def unpack(data: bytes, limit: int=256*1024*1024) -> bytes:
    # LZMA-alone for kernel; XZ for separate initrd. Explicit bounds prevent memory blowups.
    dec=lzma.LZMADecompressor(format=lzma.FORMAT_AUTO,memlimit=256*1024*1024)
    out=dec.decompress(data,max_length=limit+1)
    require(len(out)<=limit and dec.eof,'Compressed stream incomplete or exceeds limit')
    require(not dec.unused_data,'Unexpected trailing compressed data')
    return out


def read_cpio(blob: bytes):
    pos=0; files={}
    while pos+110<=len(blob):
        h=blob[pos:pos+110]; require(h[:6]==b'070701','Only newc CPIO is accepted')
        try: fields=[int(h[6+i*8:14+i*8],16) for i in range(13)]
        except ValueError as exc: raise ValueError('Invalid CPIO header') from exc
        mode,size,namelen=fields[1],fields[6],fields[11]
        require(1<=namelen<=4096 and pos+110+namelen<=len(blob),'Invalid CPIO name')
        namebytes=blob[pos+110:pos+110+namelen]; require(namebytes[-1:]==b'\0','CPIO name lacks terminator')
        name=namebytes[:-1].decode('utf-8'); pos=(pos+110+namelen+3)&~3
        require(pos+size<=len(blob),'Truncated CPIO data'); data=blob[pos:pos+size]; pos=(pos+size+3)&~3
        if name=='TRAILER!!!': return files
        while name.startswith('./'): name=name[2:]
        if name in ('','.'): continue
        require(not name.startswith('/') and '..' not in name.split('/'),'Unsafe CPIO path')
        require(name not in files,'Duplicate CPIO path'); files[name]=(mode,data)
    raise ValueError('Missing CPIO trailer')


def read_sysupgrade(path: Path):
    require(path.stat().st_size<=128*1024*1024,'Oversize TAR')
    allowed={TAR_BOARD, TAR_BOARD+'/', TAR_BOARD+'/CONTROL',TAR_BOARD+'/kernel',TAR_BOARD+'/root'}
    blobs={}; seen=set()
    with tarfile.open(path,'r:') as tf:
        for member in tf:
            require(member.name in allowed and member.name not in seen,'Unexpected/duplicate TAR member')
            seen.add(member.name)
            if member.isdir(): require(member.name.rstrip('/')==TAR_BOARD,'Unexpected directory'); continue
            require(member.isfile() and 0<member.size<96*1024*1024,'TAR link/special/empty/large file rejected')
            blobs[member.name.rsplit('/',1)[-1]]=tf.extractfile(member).read()
    require(set(blobs)=={'CONTROL','kernel','root'},'TAR must contain CONTROL, kernel and root')
    require(blobs['CONTROL'].strip()==b'BOARD=netcore_n60-pro','Unexpected CONTROL identity')
    return blobs['kernel'],blobs['root']


def write_bridge(path: Path, kernel: bytes, root: bytes, epoch: int):
    # Standard USTAR only; no PAX long-name headers, no bootloader partitions.
    with tarfile.open(path,'w',format=tarfile.USTAR_FORMAT) as tf:
        d=tarfile.TarInfo(TAR_BOARD+'/'); d.type=tarfile.DIRTYPE; d.mode=0o755; d.mtime=epoch; tf.addfile(d)
        for name,data in [('CONTROL',b'BOARD=netcore_n60-pro\n'),('kernel',kernel),('root',root)]:
            item=tarfile.TarInfo(TAR_BOARD+'/'+name); item.size=len(data); item.mode=0o644; item.mtime=epoch
            tf.addfile(item,io.BytesIO(data))
    require(read_sysupgrade(path)==(kernel,root),'Generated archive read-back differs from input')


def prune_parent_defaults(text: str) -> str:
    require('KERNEL_PATCHVER:=6.6' in text and 'luci-app-ttyd' in text and 'automount' in text,
            'Unexpected parent target defaults; review pinned source')
    pattern=r'^DEFAULT_PACKAGES \+=\s*\\\n(?:[^\n]*\\\n)*[^\n]*\n'
    text,count=re.subn(pattern,'DEFAULT_PACKAGES += kmod-leds-gpio kmod-gpio-button-hotplug ethtool kmod-usb2 kmod-usb3 usbutils\n',text,count=1,flags=re.M)
    require(count==1,'Parent target defaults could not be pruned')
    require(text.count('include $(INCLUDE_DIR)/target.mk')==1,'Unexpected parent target include')
    return text.replace('include $(INCLUDE_DIR)/target.mk','DEVICE_TYPE:=basic\ninclude $(INCLUDE_DIR)/target.mk')


def disable_n60pro_uboot_default(text: str) -> str:
    """Keep the selected device's hidden U-Boot package out of rescue builds."""
    pattern = r'^define U-Boot/mt7986_netcore_n60-pro\n.*?^endef$'
    matches = list(re.finditer(pattern, text, re.M | re.S))
    require(len(matches) == 1, 'Missing/ambiguous N60 Pro U-Boot variant')
    expected = '''define U-Boot/mt7986_netcore_n60-pro
  NAME:=Netcore N60 Pro
  BUILD_SUBTARGET:=filogic
  BUILD_DEVICES:=netcore_n60-pro
  UBOOT_CONFIG:=mt7986_netcore_n60-pro
  UBOOT_IMAGE:=u-boot.fip
  BL2_BOOTDEV:=spim-nand
  BL2_SOC:=mt7986
  BL2_DDRTYPE:=ddr4
  DEPENDS:=+trusted-firmware-a-mt7986-spim-nand-ddr4
endef'''
    match = matches[0]
    require(match.group() == expected, 'Unexpected N60 Pro U-Boot baseline')
    replacement = expected.replace('  BUILD_DEVICES:=netcore_n60-pro\n',
                                   '  BUILD_DEVICES:=netcore_n60-pro\n  DEFAULT:=n\n')
    return text[:match.start()] + replacement + text[match.end():]


def enable_ppe_conntrack_mark(text: str) -> str:
    """Supply the two bools required by the pinned vendor PPE's ct->mark reads."""
    lines = text.splitlines()
    require(lines.count('CONFIG_NF_CONNTRACK=y') == 1 and lines.count('CONFIG_NETFILTER=y') == 1,
            'Unexpected PPE conntrack baseline')
    require(not re.search(r'^(?:# )?CONFIG_(?:NF_CONNTRACK_MARK|NETFILTER_ADVANCED)\b', text, re.M),
            'Unexpected PPE conntrack mark baseline')
    text = text.replace('CONFIG_NETFILTER=y\n', 'CONFIG_NETFILTER=y\nCONFIG_NETFILTER_ADVANCED=y\n')
    return text.replace('CONFIG_NF_CONNTRACK=y\n', 'CONFIG_NF_CONNTRACK=y\nCONFIG_NF_CONNTRACK_MARK=y\n')


def install_kernel_compat(src: Path, out: Path):
    """Install the late no-HNAT fix only over the reviewed upstream baseline."""
    for relative, expected in HNAT_BASELINE_HASHES.items():
        baseline = src / relative
        require(baseline.is_file(), f'Missing kernel patch baseline: {relative}')
        require(hashlib.sha256(baseline.read_bytes()).hexdigest() == expected,
                f'Unexpected kernel patch baseline: {relative}')
    patch = BASE / 'patches' / HNAT_COMPAT_PATCH
    require(patch.is_file(), f'Missing kernel compatibility patch: {patch}')
    payload = patch.read_bytes()
    require(bool(payload), f'Empty kernel compatibility patch: {patch}')
    target = src / 'target/linux/mediatek/patches-6.6' / HNAT_COMPAT_PATCH
    require(not target.exists(), f'Kernel compatibility patch already exists: {target}')
    target.write_bytes(payload)
    (out / HNAT_COMPAT_PATCH).write_bytes(payload)
    (out / 'kernel-compatibility.json').write_text(json.dumps({
        'patch': HNAT_COMPAT_PATCH,
        'sha256': hashlib.sha256(payload).hexdigest(),
        'upstream_sha256': HNAT_BASELINE_HASHES,
    }, indent=2) + '\n', encoding='utf-8')
    print(f'Installed kernel compatibility patch: {HNAT_COMPAT_PATCH}')


def prepare(src: Path, out: Path, layout: str, key: str):
    require((src/'.git').is_dir(),'Use a fresh Git checkout, not your backup folder')
    out.mkdir(parents=True,exist_ok=True); key=validate_key(key)
    source_lock=json.loads((BASE/'config/source-lock.json').read_text())
    actual=run(['git','-C',src,'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    require(actual==source_lock['source']['sha'],'Checkout differs from source-lock.json')
    install_kernel_compat(src, out)
    uboot=src/'package/boot/uboot-mediatek/Makefile'
    uboot.write_text(disable_n60pro_uboot_default(uboot.read_text()))
    kernel_config=src/'target/linux/mediatek/filogic/config-6.6'
    kernel_config.write_text(enable_ppe_conntrack_mark(kernel_config.read_text()))
    dts=src/'target/linux/mediatek/dts/mt7986a-netcore-n60-pro.dts'
    original=dts.read_text(); changed=patch_dts(original,layout); dts.write_text(changed)
    # Change only the selected device's package list/recipe, not other boards.
    mk=src/'target/linux/mediatek/image/filogic.mk'; text=mk.read_text()
    pattern=r'^define Device/netcore_n60-pro\n.*?^endef$'
    require(len(re.findall(pattern,text,re.M|re.S))==1,'Ambiguous N60 Pro device recipe')
    replacement='''define Device/netcore_n60-pro
  DEVICE_VENDOR := Netcore
  DEVICE_MODEL := N60 Pro
  DEVICE_DTS := mt7986a-netcore-n60-pro
  DEVICE_DTS_DIR := ../dts
  DEVICE_PACKAGES := kmod-usb3 kmod-usb-ledtrig-usbport
  BLOCKSIZE := 128k
  PAGESIZE := 2048
  KERNEL_IN_UBI := 1
  IMAGES := sysupgrade.bin
  ARTIFACTS :=
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
endef'''
    mk.write_text(re.sub(pattern,replacement,text,count=1,flags=re.M|re.S))
    # Remove GUI/automount/Wi-Fi defaults for this disposable rescue-only source checkout.
    parent=src/'target/linux/mediatek/Makefile'
    parent.write_text(prune_parent_defaults(parent.read_text()))
    target=src/'target/linux/mediatek/filogic/target.mk'; t=target.read_text()
    require('wpad-openssl' in t,'Unexpected target defaults')
    target.write_text('DEVICE_TYPE:=basic\n'+t.replace(' wpad-openssl',''))
    target=src/'include/target.mk'; t=target.read_text()
    pattern=r'^DEFAULT_PACKAGES\.tweak:=\\\n(?:[^\n]*\\\n)*[^\n]*\n'
    t,count=re.subn(pattern,'DEFAULT_PACKAGES.tweak:=\n',t,count=1,flags=re.M)
    require(count==1,'Unexpected tweak defaults block'); target.write_text(t)
    # The pinned upstream ships a files/ overlay; don't inherit passwords or extra defaults.
    overlay=src/'files'
    if overlay.exists(): shutil.rmtree(overlay)
    shutil.copytree(BASE/'overlay',overlay)
    auth=overlay/'etc/dropbear'; auth.mkdir(parents=True,exist_ok=True); auth.chmod(0o700)
    (auth/'authorized_keys').write_text(key); (auth/'authorized_keys').chmod(0o600)
    for path in (overlay/'usr/sbin').glob('*'): path.chmod(0o755)
    (overlay/'etc/board.d/02_network').chmod(0o755)
    (overlay/'etc/n60pro-rescue-layout').write_text(layout+'\n')
    (overlay/'etc/n60pro-rescue-source').write_text(actual+'\n')
    shutil.copyfile(BASE/'config/rescue.config',src/'.config')
    (out/'source-dts-before.dts').write_text(original); (out/'source-dts-after.dts').write_text(changed)
    (out/'source-lock.json').write_text(json.dumps(source_lock,indent=2)+'\n')
    (out/'build-assumptions.json').write_text(json.dumps({
        'board':BOARD,'layout':layout,'ubi_start':'0x00580000','ubi_size':f'0x{LAYOUTS[layout]:08x}',
        'recipe_repository':os.environ.get('GITHUB_REPOSITORY','local'),
        'recipe_revision':os.environ.get('GITHUB_SHA','not-recorded'),
        'ssh_public_line_sha256':hashlib.sha256(key.encode()).hexdigest(),
        'memory_policy':'upstream 512 MiB DTS retained; existing bootloader may fix up memory',
        'nmbm_policy':'upstream reserve policy retained; not proven to match physical chip',
        'protected_linux_partitions':list(PARTS),'runtime_ubi_read_only':False,
        'flash_hardware_test':'NOT_PERFORMED','network':'192.168.6.1/24; LAN only; key-auth SSH',
        'root_and_fit_source':'same source tree, feeds, configuration and build run'},indent=2)+'\n')


def read_package_names(src: Path) -> set[str]:
    """Read real package identities, not package-specific Kconfig feature flags.

    package-dumpinfo.mk emits Package: records plus free-form Description/Config
    blocks ending in @@. A CONFIG_PACKAGE_ prefix alone is not a package ID.
    Missing or malformed metadata must never disable the package safety gate.
    """
    path = src / 'tmp/.packageinfo'
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError(f'Cannot read package metadata {path}; run make defconfig first') from exc
    names: set[str] = set()
    in_block = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if in_block:
            if line == '@@':
                in_block = False
            continue
        if line.startswith(('Description:', 'Config:')):
            in_block = True
            continue
        if line.startswith('Package:'):
            name = line[len('Package:'):].strip()
            require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+\-]*', name)),
                    f'Invalid package metadata Package: record at {path}:{line_number}')
            # Feed overrides may repeat identities. They are still the same symbol.
            names.add(name)
    require(not in_block, f'Unterminated package metadata block in {path}')
    require(bool(names), f'No Package: records in package metadata {path}')
    # These packages are required by this recipe. A partial index is not usable.
    missing = {'dropbear', 'ubi-utils', 'mtd', 'dnsmasq'} - names
    require(not missing, f'Incomplete package metadata {path}: missing {", ".join(sorted(missing))}')
    return names


def check_config(src: Path):
    txt=(src/'.config').read_text(); entries=dict(re.findall(r'^(CONFIG_[^=\s]+)=(.*)$',txt,re.M))
    for s in ['TARGET_mediatek','TARGET_mediatek_filogic','TARGET_mediatek_filogic_DEVICE_netcore_n60-pro',
              'TARGET_ROOTFS_INITRAMFS','TARGET_ROOTFS_INITRAMFS_SEPARATE','TARGET_INITRAMFS_COMPRESSION_XZ',
              'TARGET_ROOTFS_SQUASHFS','PACKAGE_dropbear','PACKAGE_ubi-utils','PACKAGE_mtd','PACKAGE_dnsmasq']:
        require(entries.get('CONFIG_'+s)=='y',f'Required Kconfig symbol not enabled: {s}')
    # Only symbols whose entire suffix is a real package name select packages.
    # e.g. luci-app-passwall_INCLUDE_Haproxy may be y while its parent is disabled.
    for pkg in sorted(read_package_names(src)):
        if entries.get('CONFIG_PACKAGE_'+pkg) != 'y':
            continue
        require(not (pkg.startswith(('luci-','wpad','hostapd','kmod-mt79','kmod-mt_wifi','uboot-mediatek','arm-trusted-firmware','u-boot-','trusted-firmware-a-')) or pkg in ['luci','automount','default-settings','default-settings-chn','dockerd']),f'Unexpected rescue package selected: {pkg}')
    targets=[k for k,v in entries.items() if '_DEVICE_' in k and k.startswith('CONFIG_TARGET_') and v=='y']
    require(targets==['CONFIG_TARGET_mediatek_filogic_DEVICE_netcore_n60-pro'],'More than one target selected')


def check_dtb(data: bytes, layout: str):
    tree=parse_fdt(data)
    require(BOARD.encode()+b'\0' in tree['/'].get('compatible',b''),'FIT DTB has wrong board')
    flashes=[p for p,d in tree.items() if 'mediatek,nmbm' in d]
    require(len(flashes)==1,'NMBM property missing/ambiguous')
    parts={}
    for p,d in tree.items():
        if not p.startswith(flashes[0]+'/partitions/'): continue
        if 'label' in d and 'reg' in d:
            label=cstr(d['label']); require(len(d['reg'])==8,'Unexpected partition reg cells')
            require(label not in parts,'Duplicate partition label'); parts[label]=struct.unpack('>II',d['reg'])
            if label in PARTS: require('read-only' in d, f'{label} not protected in Linux DTS')
    require(parts==dict(PARTS,ubi=(0x580000,LAYOUTS[layout])),'Compiled DTB partitions do not match selected policy')
    return tree


def verify_fit(blob: bytes, need_initrd: bool):
    tree=parse_fdt(blob); cfg='/configurations/'+cstr(tree['/configurations']['default']); conf=tree[cfg]
    required=['kernel','fdt']+(['ramdisk'] if need_initrd else [])
    result={}
    for prop in required:
        path='/images/'+cstr(conf[prop]); props=tree[path]
        require('data' in props and 'data-position' not in props and 'data-offset' not in props,'FIT must use inline data')
        data=props['data']; verify_hashes(tree,path,data); result[prop]=(props,data)
    k=result['kernel'][0]
    require(cstr(k['type'])=='kernel' and cstr(k['arch'])=='arm64' and cstr(k['os'])=='linux','Unexpected kernel type/architecture')
    require(cstr(k['compression'])=='lzma','Expected LZMA kernel')
    for prop in ['load','entry']: require(int.from_bytes(k[prop],'big')==0x48000000,f'Unexpected {prop} address')
    return result


def compare_variants(rescue, normal):
    # OpenWrt can recompile the initramfs variant with different CONFIG_RD_* flags.
    # Same source/run does NOT require bit-identical normal and initramfs kernels.
    require(rescue['kernel'][0].get('description') == normal['kernel'][0].get('description'),
            'Normal/rescue kernel descriptions differ')
    require(rescue['fdt'][1] == normal['fdt'][1], 'Normal/rescue DTBs differ')
    return rescue['kernel'][1] == normal['kernel'][1]


def verify_squashfs(path: Path, log: Path):
    data=path.read_bytes(); require(len(data)>=96,'Short SquashFS')
    require(data[:4]==b'hsqs' and struct.unpack_from('<H',data,28)[0]==4,'Not SquashFS v4')
    used=struct.unpack_from('<Q',data,40)[0]; require(96<=used<=len(data),'SquashFS bytes_used exceeds payload')
    listing=run(['unsquashfs','-ll',path],capture_output=True,text=True).stdout
    log.write_text(listing)
    regular=[]
    for line in listing.splitlines():
        if not line.startswith('-'): continue
        fields=line.split(None,5); require(len(fields)==6,'Unexpected unsquashfs listing format')
        require(fields[5].startswith('squashfs-root/'),'Unexpected unsquashfs path prefix')
        regular.append(fields[5][len('squashfs-root/'):])
    require(len(regular)>20,'Too few regular rootfs files')
    # Read every regular file without extracting nodes, symlinks, ownership or xattrs.
    for i in range(0,len(regular),40):
        with open(os.devnull,'wb') as sink:
            run(['unsquashfs','-cat',path,*regular[i:i+40]],stdout=sink,stderr=subprocess.PIPE)
    return len(regular)


def package(src: Path, out: Path, layout: str):
    require(layout in LAYOUTS,'Invalid layout'); check_config(src)
    target=src/'bin/targets/mediatek/filogic'
    def unique(pattern):
        xs=list(target.glob(pattern)); require(len(xs)==1,f'Expected exactly one {pattern}, found {len(xs)}'); return xs[0]
    fitpath=unique('*-netcore_n60-pro-initramfs-kernel.bin')
    normalpath=unique('*-netcore_n60-pro-squashfs-sysupgrade.bin')
    fit=fitpath.read_bytes(); normal,root=read_sysupgrade(normalpath)
    # Keep >=8 MiB between source buffer at 0x46000000 and kernel load at 0x48000000.
    require(len(fit)<=24*1024*1024,'Rescue FIT exceeds conservative 24 MiB source-buffer limit')
    rec=verify_fit(fit,True); ordinary=verify_fit(normal,False)
    variants_identical=compare_variants(rec,ordinary)
    dtb=rec['fdt'][1]; check_dtb(dtb,layout)
    kernel=unpack(rec['kernel'][1],64*1024*1024)
    require(len(kernel)>=64 and kernel[56:60]==b'ARM\x64','Not ARM64 Image')
    image_size=struct.unpack_from('<Q',kernel,16)[0]
    require(len(kernel)<=image_size<=64*1024*1024,'Unexpected ARM64 image_size')
    require(0x46000000+len(fit)<=0x48000000,'FIT source/kernel destination overlap')
    rd=rec['ramdisk'][1]; require(rd.startswith(b'\xfd7zXZ\x00'),'Expected XZ initrd')
    entries=read_cpio(unpack(rd))
    needed=['init','sbin/init','bin/busybox','usr/sbin/dropbear','sbin/mtd','usr/sbin/ubinfo',
            'usr/sbin/ubiformat','usr/sbin/ubiupdatevol','etc/dropbear/authorized_keys',
            'etc/config/network','etc/config/dropbear','etc/board.d/02_network','usr/sbin/rescue-report']
    for name in needed: require(name in entries,f'Missing initrd entry: {name}')
    require(b'INITRAMFS=1' in entries['init'][1],'Initrd startup marker missing')
    require('lib/preinit/80_mount_root' in entries and b'"$INITRAMFS" = "1"' in entries['lib/preinit/80_mount_root'][1],'Initramfs root-mount guard missing')
    for svc in ['dropbear','network','dnsmasq']:
        require(any(p.startswith('etc/rc.d/S') and p.endswith(svc) for p in entries),f'{svc} boot enable symlink missing')
    auth=(src/'files/etc/dropbear/authorized_keys').read_bytes()
    require(entries['etc/dropbear/authorized_keys'][1]==auth,'SSH public key missing or changed')
    require(b"192.168.6.1" in entries['etc/config/network'][1],'Fixed LAN config missing')
    # Full SquashFS regular-file decompression; never run target ARM executables.
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='n60-root-') as temp:
        rp=Path(temp)/'root.squashfs'; rp.write_bytes(root)
        count=verify_squashfs(rp,out/'rootfs-file-list.txt')
        module_names=[n for n in entries if n.startswith('lib/modules/') and n.endswith(('.ko','.ko.gz','.ko.xz','.ko.zst'))]
        require(bool(module_names),'No kernel modules found in initrd')
        for name in ['etc/dropbear/authorized_keys','etc/config/network','etc/config/dropbear','etc/board.d/02_network','etc/openwrt_release',*module_names]:
            value=run(['unsquashfs','-cat',rp,name],capture_output=True).stdout
            require(name in entries and value==entries[name][1],f'Normal rootfs/initrd differ: {name}')
    epoch=int(run(['git','-C',src,'show','-s','--format=%ct','HEAD'],capture_output=True,text=True).stdout.strip())
    staged=out/'_staged'; staged.mkdir(exist_ok=False)
    # Do not expose binaries as completed artifacts until all image checks pass.
    try:
        prefix=f'n60pro-{layout}'
        tarpath=staged/(prefix+'-rescue-web-EXPERIMENTAL.bin')
        write_bridge(tarpath,fit,root,epoch)
        run(['tar','-tf',tarpath],stdout=subprocess.DEVNULL)
        (staged/(prefix+'-initramfs-kernel.bin')).write_bytes(fit)
        (staged/'compiled-device-tree.dtb').write_bytes(dtb)
        with (staged/'compiled-device-tree.dts').open('w') as f:
            run(['dtc','-I','dtb','-O','dts',staged/'compiled-device-tree.dtb'],stdout=f,stderr=subprocess.PIPE)
        report={
            'status':'OFFLINE_VALIDATED_NOT_BOOT_TESTED','board':BOARD,'layout':layout,
            'candidate':tarpath.name,'candidate_size':tarpath.stat().st_size,
            'candidate_sha256':hashlib.sha256(tarpath.read_bytes()).hexdigest(),
            'candidate_md5':hashlib.md5(tarpath.read_bytes()).hexdigest(),
            'fit_size':len(fit),'fit_sha256':hashlib.sha256(fit).hexdigest(),
            'kernel_load':'0x48000000','kernel_entry':'0x48000000','kernel_image_size':image_size,
            'initrd_members':len(entries),'root_size':len(root),'root_regular_files_read':count,
            'same_kernel_description_and_dtb':'PASS','kernel_variants_byte_identical':variants_identical,
            'same_build_root_config_and_release':'PASS','root_and_initrd_module_payloads_match':len(module_names),
            'fit_internal_hashes':'PASS','partition_check':'PASS','root_full_regular_file_read':'PASS',
            'forbidden_tar_members':'ABSENT','boot_test':'NOT_PERFORMED','router_contact':'NONE',
            'ssh':'root@192.168.6.1 port 22; Ed25519 key only','wifi':'NOT_INCLUDED',
            'warning':'Writing the web candidate is a NAND operation. It may erase UBI contents and still fail to boot.'}
        (staged/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
        (staged/'DO-NOT-AUTO-FLASH.txt').write_text('Experimental N60 Pro rescue candidate. No physical boot test.\nNot for BL2/FIP pages; not a vendor factory image.\nDo not assume RAM-rootfs implies a write-free upload.\nDo not migrate the bootloader or restore backups automatically.\n')
        for p in staged.iterdir(): shutil.move(str(p),out/p.name)
    finally:
        if staged.exists(): shutil.rmtree(staged)
    for name in ['.config','feeds.conf']:
        shutil.copyfile(src/name,out/('expanded.config' if name=='.config' else 'locked-feeds.conf'))
    with (out/'source.patch').open('w') as f: run(['git','-C',src,'diff','--no-ext-diff'],stdout=f)
    shutil.copyfile(normalpath,out/'normal-sysupgrade-SAMEBUILD-REFERENCE.tar')
    for p in target.glob('*.manifest'): shutil.copyfile(p,out/p.name)
    items=sorted(p for p in out.iterdir() if p.is_file() and p.name!='SHA256SUMS')
    (out/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in items))
    print(json.dumps(report,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('command',choices=['prepare','check-config','package'])
    parser.add_argument('--source',type=Path,required=True); parser.add_argument('--out',type=Path,default=Path('dist'))
    parser.add_argument('--layout',choices=LAYOUTS,default='linux-original-474m')
    args=parser.parse_args()
    if args.command=='prepare': prepare(args.source,args.out,args.layout,os.environ.get('RESCUE_SSH_PUBLIC_KEY',''))
    elif args.command=='check-config': check_config(args.source)
    else: package(args.source,args.out,args.layout)

if __name__=='__main__': main()
