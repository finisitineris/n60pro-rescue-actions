# 验证记录

生成日期：2026-09-20。

## 本地确实执行过

- `python3 -m unittest discover -s tests -v`：17 项通过。包含 FDT 正常/截断/重复属性、CPIO 正常/截断/路径穿越/根目录、LZMA/XZ 输出边界、公钥输入、两种 DTS 补丁与重复应用拒绝、TAR 读回与非允许成员拒绝、内核变体的正确区别、平台默认包裁剪。
- 测试先经历未实现状态的失败，然后通过；详细最终输出见 `unit-test-results.txt`。
- `python3 -m py_compile scripts/*.py`：通过。
- `bash -n scripts/build.sh`、`sh -n` 两个 overlay shell 脚本：通过。
- 两个 Actions YAML 经 PyYAML 语法解析；检查 permissions=contents:read、actions 全提交 SHA 固定、工作流输入不直接拼进 shell：通过。这不等于 GitHub 服务器已经接受/运行了 workflow。
- 用当前会话真实 FIT 头/尾/中段样本测试本解析器：元数据解析、load/entry、完整提取的 DTB CRC32/SHA1 一致性通过。仅在内存中用零补齐未收到区段，**未校验那些缺失 payload，也未把稀疏样本输出为镜像**。记录见 `real-fit-metadata-check.txt`；用户样本没有收入这个仓库。
- 人工对照固定上游提交的 target Makefile、默认包、镜像配方、Config-images.in、kernel-defaults.mk、N60 Pro DTS 和 ubi-utils 安装定义。

## 尚未执行

- 没有在这里 clone 全部锁定源码、运行 `make defconfig` 或交叉编译全固件；当前制作环境无法联网拉取完整源码，也未启动你的 GitHub Actions。
- 没有在本地运行 `unsquashfs`、`dtc` 的固件后处理链路。工具将在 GitHub job 中安装并运行；任何失败都会阻止候选固件 artifact 的发布。
- 没有读取设备当前 Flash、没有运行 ARM 目标程序、没有实机启动/刷写测试。
- 因此不声称这个配方已经完成首次全量编译或生成了保证能启动的镜像。交付的是可审阅的构建/校验配方，不是经实机认证的固件。

## 复查要点

普通内核和 initramfs 内核即使同源，也可能因 initrd 解压配置变化产生不同字节。本配方不错误地强制两份内核哈希相同；它比较版本描述、DTB、内核模块及配置，另外记录是否恰好同字节。源码版本固定也不等于所有外部依赖可用或跨环境字节级可复现。

首次 Actions 运行的 `configuration-check` 和 `package` 断言属于真实构建门禁，不应为了输出文件而注释掉。首次运行失败时，保留首个实际错误及原日志；不要盲目强刷未经过门禁的文件。
