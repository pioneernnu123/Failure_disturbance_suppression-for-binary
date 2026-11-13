# 内存失效扰动抑制

适用于 RISC-V 服务器的现有 Linux 内核。编译需要与运行内核匹配的头文件、配置和 `Module.symvers`。从项目根目录开始执行。

## 一 编译驱动和 memtester

```bash
cd rampage/module
make KDIR=/home/lzu/sg2042-vendor-kernel-6.1
cd ../../memtester-master
make
cd ..
```

上面的 `KDIR` 是在 `k8snode1` 上验证过的构建目录。其他打包环境应使用与目标内核兼容的构建目录。
在 `rampage/module` 目录运行 `sh ./rebuild.sh` 可一次编译并加载。脚本调用
`make`，由 Makefile 使用默认的内核构建目录。当前 `k8snode1` 的默认目录缺失，
在该服务器上执行 `KDIR=/home/lzu/sg2042-vendor-kernel-6.1 sh ./rebuild.sh`。

## 二 加载驱动

替换已加载的旧驱动时，先执行 `sudo rmmod phys_mem`。

```bash
sudo insmod rampage/module/phys_mem.ko
```

## 三 持续检测和手动注入

窗口一从项目根目录执行。

```bash
cd rampage/userspace
sudo python3 main.py \
    -t memtester \
    --memtester-args="-i 5" \
    --memtester-inject-type=0 \
    -a slow \
    --frames-per-check=50 \
    --scan-mode=local \
    --max-memory=2G \
    --logfile=./memtester-slow.log
```

`--frames-per-check=50` 每次最多分配并检测 50 页。`-i 5` 是从 0 开始的页索引。局部模式每轮累计最多测试 2 GiB 的驱动分配页，达到上限后进入下一轮。`--logfile` 也可填写原来的绝对路径，批次号和每次检测的结果都会写入该文件。

窗口二也从项目根目录执行。

```bash
cd rampage/userspace
sudo python3 injection_control.py
```

输入 0～7 并回车。0 表示无注入，1 表示地址固定错误。下一次 memtester 调用会读取新编号，后续调用继续沿用该编号，直到再次输入。完成本用例后，在窗口一按 Ctrl+C，当前检测结束并提交结果后退出。窗口二输入 `q` 并回车。

## 四 运行大纲的四项自动验收

从 `rampage/userspace` 目录执行。

```bash
sudo python3 run_memory_test.py --memtester=../../memtester-master/memtester
```

程序先跑无注入基线，再依次执行四项用例。通过时结果为 `5/5`、`3/3`、`2/2`、`5/5`。每轮日志和 `summary.json` 自动写入终端打印的结果目录。

## 五 查看隔离记录并按批次恢复

两种运行方式都会打印 `RUN_ID`。在检测退出后，把下面的“批次号”替换成实际数字。在 `rampage/userspace` 目录查询。

```bash
sudo ./phys_memctl status --run-id 批次号
```

保存“已隔离”记录并核对 PFN 和字节偏移。“已隔离”表示驱动仍扣留该页。验收时在检测日志中核对 `map_refs=0` 和 `module_refs=1`，然后执行恢复。

```bash
sudo ./phys_memctl restore --run-id 批次号 --simulated-only 2>&1 | tee restore.log
sudo ./phys_memctl status --run-id 批次号 | tee -a restore.log
```

恢复结果应显示 `failed=0`，随后查询应显示 `simulated=0`。来源不明的页继续扣留。
