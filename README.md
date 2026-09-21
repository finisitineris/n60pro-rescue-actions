# N60 Pro：从源码构建的临时 Linux / SSH 救援镜像

**用途：为现有旧式 NMBM / UBI / Web U-Boot 构建一个救援候选。不是官方固件，不是 BL2/FIP 更新包，不是新分区方案迁移器。**

这是 GitHub Actions 构建配方，不是已经编译好的镜像。首次实际交叉编译需要在你的 GitHub Actions 运行；附带的验证记录仅覆盖脚本离线测试。**构建成功和静态校验成功，均不等于在你的路由器上启动成功。**

## 与上一个本地拼包方案的区别

旧方案把发布包中的救援 FIT 和另一个发布包的 SquashFS 组合，备用 root 与内核是否兼容没有验证。本方案在**同一份源码、同一套 feeds、同一份配置、同一个工作流运行**中生成内核、initrd 和 SquashFS，然后将完整救援 FIT 与本次新生成的 root 组合。

普通内核与 initramfs 内核可能因 CONFIG_RD_* 等配置产生不同二进制，不能把“两个 kernel 必须逐字节相同”作为同源判断。本工具比较版本描述、DTB、root/内存盘中的内核模块及关键配置，并保存源码提交和构建补丁；仍不声称已经完成所有 ABI/运行时验证。

## 适用背景与假设

目标：Netcore N60 Pro / `netcore,n60-pro` / MT7986，已有记录约 2 GiB RAM、512 MiB NAND，以及旧 NMBM U-Boot。不是给原厂 128 MiB 机器通用使用。

保留现有 BL2/FIP，不编译、上传或写入新的 Bootloader。源码中的 NMBM 标志及保留区策略保持不变；**不能据此保证与实际 NAND 型号/坏块表一致**。DTS 保留上游的 512 MiB 内存描述，不在内核设备树硬写 2 GiB；现有 Bootloader 是否修正内存仍需实机确认。512 MiB 描述不是对你的物理 RAM 的重新判定。

### 分区选项

| Actions 输入 `layout` | UBI 起点 | Linux DTS 中 UBI 长度 | 依据 |
|---|---:|---:|---|
| **linux-original-474m（默认）** | `0x00580000` | `0x1da80000` = 474.5 MiB | 你此前正常系统 `/proc/mtd` 中的长度；这里起点按原 FIP/源码对应布局取值 |
| uboot-default-460m | `0x00580000` | `0x1cc00000` = 460 MiB | 原 FIP 内置 `471040k(ubi)` 的长度 |

选择一个选项只是在编译 Linux DTS，**不改变 U-Boot 自己的分区表、不迁移 NMBM、不擦除或格式化任何设备**。这两个数值是不同的观察/假设，不是已经确定了故障原因。默认沿用旧 Linux 视图，不做 400/506.5 MiB 扩容。不要把两个选项当作轮流盲刷清单。

前四个分区偏移/长度不变，并在生成的 Linux DTS 中设为 read-only：bl2、u-boot-env、factory、fip。**UBI 未设为只读，NMBM/UBI 驱动仍可能进行元数据操作；不承诺启动后完全零写入。**这一内核保护也不约束 U-Boot 自身的刷写行为。

## 第一次使用

### 1. 将配方放入自己的仓库

解压工具包后，新建一个仓库，例如 `n60pro-rescue-actions`。把本目录**内部的所有目录/文件**提交到仓库根目录，不要把整个 ZIP 当作唯一文件上传。

仓库应呈现：

```text
.github/workflows/build-rescue.yml
.github/workflows/check-scripts.yml
config/source-lock.json
config/rescue.config
scripts/rescue.py
scripts/checkout_sources.py
scripts/build.sh
patches/9999-99-n60pro-rescue-no-hnat.patch
overlay/...
tests/test_rescue.py
README.md
```

`.github` 是点开头的目录，不能遗漏。用 Git 提交会包含它；用网页拖拽上传时也要确认它实际存在。工作流文件应在默认分支中。工作流使用只读 contents 权限，不需要 PAT、路由器登录密码、FIP、factory 或原机备份。

一次普通 push 只触发约束为 10 分钟的**脚本测试**，不编译整个固件。固件构建只由你手动运行。

本配方包含无 HNAT 救援配置的 MediaTek 网卡兼容补丁。`prepare` 会核对上游文件指纹，
将补丁放到内核补丁序列末尾，并把补丁及 `kernel-compatibility.json` 保存到产物中。
更新仓库时必须一并提交 `patches/`。原因和验证范围见 [网卡编译修复说明](docs/FIX-MTK-NO-HNAT.md)。

### 2. 准备一个 SSH Ed25519 公钥

本镜像不设置通用默认 root 密码，采用你自己的 SSH 公钥登录。**只提供 `.pub`，私钥留在电脑。**

已有 Ed25519 公钥可在 PowerShell 查看：

```powershell
Get-Content "$HOME\.ssh\id_ed25519.pub"
```

没有密钥时，可用下面的专用名称生成。已有同名文件会停止，避免误覆盖：

```powershell
$Key = Join-Path $HOME '.ssh\n60pro_rescue_ed25519'
New-Item -ItemType Directory -Force (Split-Path $Key) | Out-Null
if ((Test-Path $Key) -or (Test-Path "$Key.pub")) {
    throw '同名密钥已存在，请使用现有公钥，不要覆盖。'
}
ssh-keygen -t ed25519 -f $Key -C n60pro-rescue
Get-Content "$Key.pub"
```

`ssh-keygen` 的密码短语是保护本机私钥的，可按自身需要设置。复制以 `ssh-ed25519 AAAA...` 开头的公钥一整行。脚本不接受私钥、RSA 密钥或带 `command=` 的 authorized_keys 选项。

### 3. 手动启动工作流

仓库 → **Actions** → **Build N60 Pro rescue** → **Run workflow**：

- `ssh_public_key`：粘贴公钥一整行。
- `layout`：首次保留 `linux-original-474m`。
- `build_jobs`：保留 `2`；机器资源充足再用 `4`。

构建会先完成小规模脚本测试，再安装依赖、检出锁定源码与 feeds、打补丁、生成配置、下载依赖、交叉编译、核验和封装。GitHub-hosted Ubuntu 24.04 是这里的目标运行环境。

首次编译包含交叉工具链，不是只打包已有内核。未在此提供实测耗时；任务上限 330 分钟。工作流只缓存下载文件，不缓存编译目录，避免旧 ABI/配置产物混入。编译出错时**不自动执行整套 `make -j1` 重试、不自动 clean 重编译**。

依赖安装后需要至少 28 GiB 空闲；不足时停止，不自动删除 runner 上其他工具。若 GitHub 托管 runner 的实际镜像可用空间不足，应使用空间更大的干净 Ubuntu runner，或由你主动处理它的空间。Actions 的可用时间/费用按你的账户和仓库情况确定。

### 4. 下载产物

只有验证通过后才上传 `n60pro-rescue-布局-运行号` artifact，其中有：

| 文件 | 用途 |
|---|---|
| `n60pro-...-rescue-web-EXPERIMENTAL.bin` | 完整救援 FIT + **同次构建 root** 的 USTAR 候选；下一阶段才评估是否实机尝试 |
| `n60pro-...-initramfs-kernel.bin` | 原始完整 FIT；供支持的 RAM/TFTP 引导使用，**不是当前旧 Web 页面的直接刷写指令** |
| `normal-sysupgrade-SAMEBUILD-REFERENCE.tar` | 原生普通升级产物的参考副本；不是另一份建议盲刷的救援文件 |
| `validation.json`、`SHA256SUMS` | 完整性、布局、文件和打包检查结果 |
| `compiled-device-tree.dts/.dtb` | 实际编译进镜像的设备树 |
| `build-assumptions.json`、`source-lock.json`、`source.patch` | 假设、源码版本及实际补丁 |
| `expanded.config`、包清单、`locked-feeds.conf` | 最终配置和包来源记录 |

无论成功还是普通失败，另有 `n60pro-diagnostics-...` artifact 尽可能保存构建日志。硬超时、强制取消或 runner 丢失时，最后上传步骤可能来不及完成。

**不会自动创建 Release、不会推送源码修改、不会联系路由器，也不包含远程刷写功能。**

## 镜像内容和登录约定

这是**有线 SSH 救援版**。不包含 LuCI、Wi-Fi 驱动、OpenClash、Docker 或其他日常服务，避免再做几十 MB 的集成镜像。保留 USB 基础支持以及 `mtd`、`ubi-utils`、`uboot-envtools` 等诊断基础工具。工具存在并不表示自动运行这些工具进行写入。

网络板级初始化也替换为仅有线的 N60 Pro 版本，不再调用被移除的私有 Wi-Fi `l1dat` 工具。

固定 LAN 为 `192.168.6.1/24`，桥接 `lan1 lan2 lan3 lan4`，DHCP 分配 `192.168.6.100` 起的 20 个地址，SSH 只绑定 LAN 的 22 端口，关闭密码登录。`eth1` 不配置 WAN，关闭路由转发。实际物理口映射和驱动可用性仍需实机确认；首次启动只接隔离电脑，不接光猫/WAN。

只有在之后已经成功启动这个镜像时，才使用对应私钥连接，例如：

```powershell
ssh -i "$HOME\.ssh\n60pro_rescue_ed25519" root@192.168.6.1
```

root 用户不会有可以共享的默认密码。initramfs 的 SSH 主机密钥可能在每次启动重新生成，主机指纹变化须在确认直连的是这台设备后处理，不能全局关闭主机校验。

登录后可运行：

```sh
rescue-report
```

它读取板型、内核日志、NAND 几何、挂载、UBI 和网络状态，报告只写 `/tmp`。不调用 `ubiattach`、`ubiformat`、`mtd write`、`saveenv` 等写操作。诊断报告可能含 MAC/IP，公开提交前自行审阅。

## 自动检查范围

1. 完整提交锁定及单设备 Kconfig 检查；不允许意外选中 LuCI/Wi-Fi/Bootloader 包。
2. FIT 配置关联、inline payload、CRC32/SHA1/SHA256（存在的校验节点）、ARM64 架构与 `0x48000000` 的加载/入口地址。
3. 内核 LZMA、initrd XZ 完整解压并施加输出/内存上限；读取 newc CPIO，拒绝路径穿越及重复成员。
4. 内存盘 `/init`、INITRAMFS guard、Dropbear、网络/DHCP 启动链接、关键 UBI 工具和你提供的公钥。
5. DTB 中板型、NMBM 标志、五个分区的精确偏移/长度、前四区只读标志。
6. 对 SquashFS **所有普通文件**进行一次完整读取，不只看超级块；再比较 root 与 initrd 的关键配置/版本和内核模块字节。
7. 用 USTAR 生成四个允许成员，读取回验，计算整个候选哈希。候选没有官方 sysupgrade metadata，不能因此对 LuCI/`sysupgrade -T` 使用强制选项。
8. 对原机 FIT 源缓冲区 `0x46000000` 与内核加载 `0x48000000` 的已知范围做保守大小限制：完整 FIT 不超过 24 MiB，解压 Image 不超过 64 MiB。**这不是完整的运行时内存证明**。

“校验通过”只涉及上述静态属性。不会验证 U-Boot 当前 UBI 卷表、实际 ECC/NMBM、DDR 稳定性或板上网口。内存盘不会绕过 U-Boot 读取 kernel 卷失败；刷 Web 候选仍是 NAND 写入，可能擦除 UBI 内现有系统/配置，且仍可能不能启动。

## 后续迁移边界

当前只生成适应旧启动路径的临时系统候选。更新到新 Bootloader / 新 NMBM 或 UBI 方案 / 新正式固件是后续独立阶段，必须在临时系统中拿到实际 NAND/启动信息后决定。这里刻意保护 Linux 中的 BL2/FIP/factory/env，所以**不能拿这个救援内核当作不受限制的 Bootloader 刷写器**。不要直接套用原厂 128M N60 Pro 的迁移命令，也不要把同板名视为硬改机器兼容性证明。

## 维护和故障定位

- `config/source-lock.json` 固定了源码和四个 feeds 的完整 SHA；不跟随分支自动漂移。OS 工具链依赖、上游源码包可用性和包签名等仍会影响构建，因此不声称跨日期字节级可复现。
- 不建议为“追新”改为任意分支。更新锁文件要重新核对 DTS/设备定义。补丁遇到预期之外的源码会中止，不做模糊批量替换。
- `configuration-check` 失败：检查 `expanded.config` 和日志，查看是否有包被上游选择、依赖被移除或 Kconfig 符号消失。
- `compile` 失败：找 `dist/logs/compile.log` 中**第一处真实错误**，以及 `work/openwrt/logs`；最后的 `Error 2` 通常不足以定位。
- `package` 失败：看报错对应的静态断言；不要删断言后直接发布未验证镜像。源码不同变体的内核数据允许不同，但版本、DTB和模块/配置仍必须一致。
- 不要把任何 `mtd*.bin`、FIP、factory、私钥、订阅和配置备份提交到仓库。本方案不需要它们。

## 本地复查脚本

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
bash -n scripts/build.sh
sh -n overlay/usr/sbin/rescue-report
```

真实 Linux 编译需对应 Ubuntu 依赖和普通用户；按工作流各步执行。容器不能作为 N60 Pro 实机替身，不使用 x86 CI 的成功来证明 ARM 路由器启动。

## 参考依据

- 源码：https://github.com/padavanonly/immortalwrt-mt798x-6.6
- 固定源码提交：https://github.com/padavanonly/immortalwrt-mt798x-6.6/commit/ec9ef10efc65da1e6d1de4e2c043c0e13d08eed8
- 设备树：`target/linux/mediatek/dts/mt7986a-netcore-n60-pro.dts`
- 镜像定义：`target/linux/mediatek/image/Makefile` 和 `filogic.mk`
- 独立 initramfs 构建：`include/kernel-defaults.mk`
- 同类 N60 Pro Actions 模板（非本配方，也不等于已适配此机）：https://github.com/moshanghuakai01/netcore-n60-pro
- U-Boot FIT：https://docs.u-boot.org/en/latest/usage/fit/howto.html
- GitHub 手动运行：https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- GitHub Artifacts：https://github.com/actions/upload-artifact

此目录中新写的构建/校验脚本按 MIT 许可提供；上游 OpenWrt/ImmortalWrt、内核及包分别遵循其自身许可证，不能视为全部 MIT。
