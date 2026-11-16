# lzu-ram-1.0 binary delivery contents and completion

本说明接续最新服务器记录。交付目录固定为 /home/lzu/lzu-ram-1.0，目标内核固定为 6.1.80-lzu-ram+，保留现有工程目录名称。

## 1 Confirmed progress

记录末尾已经执行：

- 运行依赖目录改名为 runtime-rpms，平台记录改名为 PLATFORM.txt。
- 创建 sg2042-kernel61/modules.tar.gz，并读取检查，未显示新的报错。
- 内核镜像、System.map、配置、内核许可证已经收集。
- 应用主程序、控制端、改造版 memtester、自研 phys_mem 驱动和两组二进制自测已经收集。
- 两个程序入口、共享文件描述符自测和五项映射测试通过；115 个运行依赖 RPM 已下载。

未见执行记录的内容：包内启动镜像、完整设备固件、原 /boot 参考备份、cmdline.txt、page-types 和 INSTALL.md。

完整内核环境在本交付中指该版本的二进制运行文件：完整内核镜像、该版本全部已安装系统模块、启动镜像、配置、符号表、设备固件和启动参考记录。编入内核的功能在 vmlinuz 中，配置为模块的功能在 modules.tar.gz 中，自研 phys_mem.ko 随应用单独安装。page-types 是用户态检查工具，不是内核的一部分。

接收服务器已有相同发行版和正常的 SG2042 启动固件、GRUB 引导链。设备固件指 /lib/firmware 的文件，不涉及板载 BIOS、OpenSBI、UEFI 刷写。包内 sg2042-kernel61 是二进制交付子目录，不能把同名内核源码树整目录复制进来。

## 2 Final directory structure

下面是补齐后的目标结构，不表示待补文件现在已经存在：

~~~text
lzu-ram-1.0/
├── INSTALL.md
├── PLATFORM.txt
├── sg2042-kernel61/
│   ├── boot/
│   │   ├── vmlinuz-6.1.80-lzu-ram+
│   │   ├── initramfs-6.1.80-lzu-ram+.img
│   │   ├── System.map-6.1.80-lzu-ram+
│   │   └── config-6.1.80-lzu-ram+
│   ├── modules.tar.gz
│   ├── firmware.tar.gz
│   ├── boot-reference.tar.gz
│   ├── cmdline.txt
│   ├── COPYING
│   └── LICENSES/
├── Failure_disturbance_suppression-binary-riscv64/
│   ├── app/
│   │   ├── main/
│   │   │   ├── rampage
│   │   │   └── [all accompanying runtime libraries]
│   │   └── control/
│   │       ├── injection-control
│   │       └── [all accompanying runtime libraries]
│   ├── bin/
│   │   ├── memtester
│   │   └── page-types
│   ├── modules/
│   │   └── phys_mem.ko
│   ├── tests/
│   │   ├── test_memtester_mapping/
│   │   │   ├── test_memtester_mapping
│   │   │   └── [all accompanying runtime libraries]
│   │   └── test_rampage_fd/
│   │       ├── test_rampage_fd
│   │       ├── memtester
│   │       └── [all accompanying runtime libraries]
│   └── licenses/
│       ├── memtester-COPYING
│       └── RAMpage-MIT.txt
└── runtime-rpms/
    └── [115 downloaded binary RPMs]
~~~

方括号是清单说明，不是需要创建的文件或目录。app 和 tests 下保留完整 standalone 发布目录中的所有运行库。

内核文件用途：

| File | Purpose |
| --- | --- |
| vmlinuz-6.1.80-lzu-ram+ | 完整内核可执行镜像，已经编入的功能全部保留。 |
| initramfs-6.1.80-lzu-ram+.img | 打包服务器组装的通用启动镜像，提供挂载根文件系统前的启动环境。 |
| System.map-6.1.80-lzu-ram+ | 内核符号表。 |
| config-6.1.80-lzu-ram+ | 本次内核构建配置。 |
| modules.tar.gz | 该版本全部已安装的系统驱动模块和索引，不仅是内存测试使用的模块。 |
| firmware.tar.gz | 打包服务器整个 /lib/firmware 中的设备固件及随附文件。 |
| boot-reference.tar.gz | 打包服务器整个 /boot 的参考备份，包括实际存在的 EFI、GRUB、extlinux、原启动镜像等内容。 |
| cmdline.txt | 运行内核实际收到的启动参数。 |
| COPYING、LICENSES | 许可证文本。 |

modules.tar.gz 排除的 build、source 是开发源码链接；旧 phys_mem 单独排除，新 phys_mem.ko 已在应用 modules 目录。内核功能和系统驱动没有按测试需要裁剪。整个 /boot 备份只供核对，不能直接覆盖甲方启动配置或分区信息。

## 3 Complete the kernel runtime files

下面全部在打包服务器执行。已有的镜像、配置、符号表、许可证、模块压缩包和 RPM 不重复收集。

~~~bash
# 为交付内核组装通用启动镜像，输出到包内，不改动服务器正在使用的 /boot 镜像。
sudo dracut --no-hostonly --no-hostonly-cmdline \
    /home/lzu/lzu-ram-1.0/sg2042-kernel61/boot/initramfs-6.1.80-lzu-ram+.img \
    6.1.80-lzu-ram+

# 收集 /lib/firmware 中的全部设备固件。
sudo tar -czf /home/lzu/lzu-ram-1.0/sg2042-kernel61/firmware.tar.gz -C /lib firmware

# 收集完整 /boot 作为源服务器启动环境参考。
sudo tar -czf /home/lzu/lzu-ram-1.0/sg2042-kernel61/boot-reference.tar.gz -C / boot

# 让 lzu 用户拥有上述三个由 root 创建的交付文件，后续能够读取和打包。
sudo chown lzu:lzu \
    /home/lzu/lzu-ram-1.0/sg2042-kernel61/boot/initramfs-6.1.80-lzu-ram+.img \
    /home/lzu/lzu-ram-1.0/sg2042-kernel61/firmware.tar.gz \
    /home/lzu/lzu-ram-1.0/sg2042-kernel61/boot-reference.tar.gz

# 保存源服务器实际运行的内核启动参数。
cat /proc/cmdline > /home/lzu/lzu-ram-1.0/sg2042-kernel61/cmdline.txt

# 检查新启动镜像能够读取；正常清单不打印，错误仍显示。
lsinitrd /home/lzu/lzu-ram-1.0/sg2042-kernel61/boot/initramfs-6.1.80-lzu-ram+.img > /dev/null
~~~

dracut 是组装启动文件，不是重新编译内核。--no-hostonly 不把启动驱动范围限定在源服务器；--no-hostonly-cmdline 不固化源服务器的 root 等启动参数。两项用于同平台换机交付，不是性能调优参数。输出文件不存在时直接创建，未加覆盖选项；有任何报错先处理，不继续生成最终包。[dracut 059 选项说明](https://github.com/dracutdevs/dracut/blob/059/man/dracut.8.asc)

tar 的 -c 是创建，-z 是 gzip 压缩，-f 指定包名，-C 指定收集起点。这里不使用驱动列表限制或 firmware 路径筛选。

新的启动镜像随包直接安装。甲方根据自己原正常启动项添加新内核条目，保留本机 root、search、console、文件系统和路径前缀；不整体恢复源服务器 /boot。原服务器已经能启动的 initramfs 也包含在 boot-reference.tar.gz 中，供追溯。

## 4 Complete the separate acceptance tool

此工具独立于内核，供验收核对异常 PFN 的 HWPOISON 等页标志。它只读查询时不会改变内核页状态。

~~~bash
# 进入内核仓库提供的用户态工具目录。
cd /home/lzu/sg2042-kernel61/tools/vm

# 构建页状态查询工具；该命令不构建或裁剪内核。
make page-types

# 交付最终工具，不复制源码或构建目录。
cp page-types /home/lzu/lzu-ram-1.0/Failure_disturbance_suppression-binary-riscv64/bin/
~~~

WARNING 只证明检测到异常，不能独立证明异常页已经标记并隔离。甲方安装和测试时不执行 make。

## 5 Include the matching manual

在存放更新手册的电脑执行下面一条，只上传文字，不在该电脑打包。SSH 地址不同时替换 k8snode1。

~~~bash
# 上传与本次完整内核环境对应的安装手册。
scp /home/cyber/bj/openEuler/Failure_disturbance_suppression/docs/delivery/INSTALL.md lzu@k8snode1:/home/lzu/INSTALL.md
~~~

回到打包服务器：

~~~bash
# 将完整安装、启动和验收手册收入交付目录。
cp /home/lzu/INSTALL.md /home/lzu/lzu-ram-1.0/INSTALL.md
~~~

INSTALL.md 已改为直接安装包内通用 initramfs 和完整设备固件；不让甲方编译或生成启动镜像。它还包含本机 GRUB 配置、驱动加载、两组二进制自测和四项真实物理页验收操作。

## 6 Check and create the final archive

~~~bash
# 检查交付目录中的工程源码、外置字节码和构建脚本，应无输出。
find /home/lzu/lzu-ram-1.0 -type f \( \
    -name '*.py' -o -name '*.pyc' -o -name '*.pyi' \
    -o -name '*.c' -o -name '*.h' -o -name '*.cpp' \
    -o -name '*.S' -o -name '*.sh' -o -name 'Makefile' \)

# 回到交付目录上一级。
cd /home/lzu

# 将完整交付目录制作成一个大包。
tar -czf lzu-ram-1.0.tar.gz lzu-ram-1.0

# 生成传输完整性校验文件。
sha256sum lzu-ram-1.0.tar.gz > lzu-ram-1.0.tar.gz.sha256
~~~

find 若输出工程源码或构建文件，先核对来源；没有输出时继续最后三条。模块子包明确排除开发源码链接，设备固件和 /boot 参考包只收集系统运行文件。系统 RPM 是二进制包。交付不包含本工程源码树、内核源码树、.build 或 .venv-build。

最终交付 /home/lzu/lzu-ram-1.0.tar.gz、/home/lzu/lzu-ram-1.0.tar.gz.sha256、/home/lzu/INSTALL.md。

## Acceptance status

两组二进制自测通过，不代表四项真实物理页验收用例通过。当前应用 local 2G 模式扫描一轮后退出，没有同进程逐周期完全清空 PFN 状态的控制接口，也没有独立的实际注入写入确认字段。完整收集内核运行文件不会改变这些应用行为；配套手册保留了相关限制及证据要求。
