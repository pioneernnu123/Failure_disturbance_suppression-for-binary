# CPU 与内存失效扰动抑制二进制安装手册

适用于 SG2042 / riscv64、与交付环境同版本发行版的 Linux 服务器。安装过程无需编译，以下命令使用具备 sudo 权限的账户执行。

部署要求：

- 交付包存放于 `/home/lzu/`，解压目录为 `/home/lzu/lzu-ram-1.0/`。
- CPU 二进制目录为 `/home/lzu/lzu-ram-1.0/cpu-binary-riscv64/`。
- 系统具备 `depmod`、`modprobe` 及兼容的运行库。
- CPU 测试环境已配置 cgroup，目标 CPU 处于在线状态。

## 1 内存失效扰动抑制

### 1.1 解压交付包

在 `/home/lzu/` 目录执行：

```bash
# 解压交付包。
tar -xzf lzu-ram-1.0.tar.gz

# 进入交付目录。
cd lzu-ram-1.0
```

### 1.2 安装内核和应用

在解压后的 `lzu-ram-1.0` 目录执行：

```bash
# 备份本机原来的 GRUB 启动配置。
sudo cp /boot/grub/grub.cfg /boot/grub/grub.cfg.lzu-ram.bak

# 安装包内的内核镜像、initramfs、配置和符号表。
sudo cp sg2042-kernel61/boot/* /boot/

# 安装该版本完整的配套内核模块。
sudo cp -a sg2042-kernel61/lib/modules/6.1.80-lzu-ram+ /lib/modules/

# 为本次目标内核的 phys_mem 驱动准备 extra 目录。
sudo mkdir -p /lib/modules/6.1.80-lzu-ram+/extra

# 安装完整应用目录，包括主程序、控制端及其运行库。
sudo cp -a Failure_disturbance_suppression-binary-riscv64 /opt/

# 将改造版 memtester 安装到主程序固定调用的位置。
sudo cp /opt/Failure_disturbance_suppression-binary-riscv64/bin/memtester /usr/local/bin/memtester

# 安装与本次内核配套的 phys_mem 驱动。
sudo cp /opt/Failure_disturbance_suppression-binary-riscv64/modules/phys_mem.ko /lib/modules/6.1.80-lzu-ram+/extra/

# 更新目标内核的模块依赖索引。
sudo depmod 6.1.80-lzu-ram+
```

### 1.3 添加启动项并重启

```bash
# 编辑本机实际使用的 GRUB 启动配置。
sudo vi /boot/grub/grub.cfg
```

复制本机原正常启动的完整 `menuentry`，追加新条目：

- 标题：`OpenEuler Linux 6.1.80-lzu-ram+`。
- 内核文件名：`vmlinuz-6.1.80-lzu-ram+`。
- 启动镜像文件名：`initramfs-6.1.80-lzu-ram+.img`。
- 如有 `--id`，新条目使用唯一值。

以下为格式示例，分区定位、路径前缀及启动参数应沿用本机原正常启动项：

```text
menuentry 'OpenEuler Linux 6.1.80-lzu-ram+' {
        root=hd0,msdos2
        linux /boot/vmlinuz-6.1.80-lzu-ram+ console=ttyS0,115200 root=LABEL=ROOT rootfstype=ext4 rootwait rw earlycon selinux=0 LANG=en_US.UTF-8 nvme.use_threaded_int errupts=1
        initrd /boot/initramfs-6.1.80-lzu-ram+.img
}
```

保留原正常启动项和默认设置。vi 中按 `i` 编辑，完成后按 `Esc`，输入 `:wq` 保存退出。

```bash
# 重启，在 GRUB 菜单中选择新增的 lzu-ram 内核。
sudo reboot
```

首次启动从控制台选择新增的 lzu-ram 内核。启动异常时选择原正常启动项。

### 1.4 确认内核并加载驱动

重新登录后执行，`uname -r` 应输出 `6.1.80-lzu-ram+`：

```bash
# 确认运行版本，必须输出 6.1.80-lzu-ram+。
uname -r

# 加载已经安装的 phys_mem 驱动。
sudo modprobe phys_mem

# 确认驱动设备节点已经生成。
ls -l /dev/phys_mem
```

确认内核版本正确且 `/dev/phys_mem` 存在后，再运行检测程序。每次重启后重新加载 `phys_mem` 驱动。

### 1.5 启动检测及注入控制

终端一：

```bash
# 启动限定 2G 地址范围的 memtester 检测。
sudo /opt/Failure_disturbance_suppression-binary-riscv64/app/main/rampage \
    -t memtester \
    --memtester-args="-i 5" \
    --memtester-inject-type=0 \
    -a slow \
    --frames-per-check=50 \
    --scan-mode=local \
    --max-memory=2G \
    --logfile=/opt/Failure_disturbance_suppression-binary-riscv64/app/main/memtester-slow.log
```

`-i 5` 指定从 0 计数的页号 5，批次至少需成功映射 6 页，不表示注入次数。`local` 模式扫描一轮后退出，应在主程序运行期间切换注入编号。

终端二：

```bash
# 打开错误注入编号控制窗口。
sudo /opt/Failure_disturbance_suppression-binary-riscv64/app/control/injection-control
```

按测试大纲输入 `0～7` 并回车，下一次 memtester 调用生效。`0` 表示关闭注入，`q` 退出控制端；`Ctrl+C` 停止主程序。

日志目录：`/opt/Failure_disturbance_suppression-binary-riscv64/app/main/`。

- 统计日志：`memtester-slow.log`。
- 详细日志：`memtester_execution_details.log`。

## 2 CPU 失效扰动抑制

### 2.1 安装程序

准备 CPU 安装目录：

```bash
cp -a /home/lzu/lzu-ram-1.0/cpu-binary-riscv64 /home/lzu/
```

安装 CPU 程序：

```bash
cd /home/lzu/cpu-binary-riscv64
sudo mkdir -p /opt/cpu-fault
sudo cp -a . /opt/cpu-fault/
```

### 2.2 手动测试

手动测试与自动测试选择一种方式执行。CPU 与内存测试分别进行。

终端一启动监控与检测：

```bash
cd /opt/cpu-fault
sudo ./monitor.sh
```

终端二启动错误注入：

```bash
cd /opt/cpu-fault
sudo ./injector
```

在终端二先输入错误编号并回车，出现目标 CPU 提示后，再输入 CPU 编号并回车。例如向 CPU 1 注入逻辑位翻转，依次输入：

```text
1
1
```

第一个 `1` 是错误编号，第二个 `1` 是目标 CPU 编号。错误编号如下：

| 错误编号 | 错误类型 |
| --- | --- |
| 1 | 逻辑位翻转 |
| 2 | 桶形移位器异常 |
| 3 | 加法器进位链异常 |
| 4 | 乘法器部分积异常 |
| 5 | 商值偏差 |
| 6 | 除数寄存器位翻转 |
| 7 | 浮点尾数位翻转 |
| 8 | 浮点指数位翻转 |
| 9 | 浮点舍入控制异常 |
| 10 | SIMD 符号翻转 |
| 11 | 浮点 NaN 传播异常 |
| 12 | L1 数据缓存位翻转 |
| 13 | 循环计数器异常 |
| 14 | 模拟温度超限 |
| 15 | 模拟频率过低 |

提交注入后，在终端一查看检测和处置输出。下一项测试前，按测试要求恢复目标核心状态。

终端二输入 `0` 并回车可清除软件注入状态，但不能代替核心状态恢复。输入 `q` 并回车退出注入程序；终端一按 `Ctrl+C` 停止监控与检测。

### 2.3 自动测试

在一个终端执行：

```bash
cd /opt/cpu-fault
sudo bash ./run_all_tests.sh 1
```

`1` 为目标 CPU 编号，目标核心须处于在线状态。脚本按预设流程完成监控启动、错误注入、结果检查和状态恢复。

日志保存到 `/opt/cpu-fault/logs/`，目录由脚本自动创建。提前停止时按 `Ctrl+C`，脚本会尝试清理并恢复状态。

### 2.4 恢复核心状态

若提示上次测试的隔离状态尚未恢复，在 `/opt/cpu-fault/` 目录执行。以下以 CPU 1 为例：

```bash
sudo bash ./monitor.sh --restore 1
```

恢复完成后再进行下一项测试。
