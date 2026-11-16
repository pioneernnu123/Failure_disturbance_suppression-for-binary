# 内存失效扰动抑制

适用于 RISC-V 服务器的现有 Linux 内核。编译需要与运行内核匹配的头文件、配置和 `Module.symvers`。从项目根目录开始执行。

## 一 编译和安装 memtester

```bash
cd memtester-master
make
sudo make install
cd ..
```

更新本版时，请重新编译并安装 memtester，再重新编译并加载驱动。注入目标页先完成原有测试，再执行选定的注入。批次地址检查覆盖本轮参与检测的页。

## 二 编译并加载驱动

`k8snode1` 的默认内核构建目录缺失，执行以下命令。

```bash
cd rampage/module
chmod +x rebuild.sh
KDIR=/home/lzu/sg2042-vendor-kernel-6.1 ./rebuild.sh
cd ../..
```

服务器有匹配的 `/lib/modules/$(uname -r)/build` 时，可以直接执行 `./rebuild.sh`。

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

`--frames-per-check=50` 每次最多分配 50 页。`-i 5` 是从 0 开始的页索引。局部模式按每轮实际检测过的不同 PFN 计算 `--max-memory=2G`，再次分到同一个 PFN 时只计一次。驱动决定分配的 PFN。`--logfile` 也可填写原来的绝对路径。

`-s` 或 `--status_file` 指定 PFN 状态文件。局部模式默认使用 `/tmp/rampage_memtest_status_local` 且立即复测，全模式默认使用 `/tmp/memtest_status` 且间隔 24 小时复测。可用 `--retest-time` 设置间隔，单位为秒。

窗口二也从项目根目录执行。

```bash
cd rampage/userspace
sudo python3 injection_control.py
```

输入 0～7 并回车。0 表示无注入，1 表示地址固定错误。下一次 memtester 调用会读取新编号，后续调用继续沿用该编号，直到再次输入。完成本用例后，在窗口一按 Ctrl+C，当前检测结束并提交结果后退出。窗口二输入 `q` 并回车。

## 四 运行大纲的四项自动验收

从 `rampage/userspace` 目录执行。

```bash
sudo python3 run_memory_test.py
```

程序先跑无注入基线，再依次执行四项用例。通过时结果为 `5/5`、`3/3`、`2/2`、`5/5`。每轮日志和 `summary.json` 自动写入终端打印的结果目录。

## 五 查看隔离记录并按批次恢复

两种运行方式都会打印 `RUN_ID`。在检测退出后，把下面的“批次号”替换成实际数字。在 `rampage/userspace` 目录查询。

```bash
sudo ./phys_memctl status --run-id 批次号
```

保存“已隔离”记录并核对 PFN 和字节偏移。“已隔离”表示驱动仍扣留该页。日志里的 `session_pages_released` 和 `session_pages_held` 分别记录本轮自动释放和扣留的页数。验收时核对隔离页的 `map_refs=0` 和 `module_refs=1`，然后执行恢复。

```bash
sudo ./phys_memctl restore --run-id 批次号 --simulated-only 2>&1 | tee restore.log
sudo ./phys_memctl status --run-id 批次号 | tee -a restore.log
```

恢复结果应显示 `failed=0`，随后查询应显示 `simulated=0`。来源不明的页继续扣留。
已恢复的记录在表满时按恢复顺序复用表项。需要长期留存时，保存检测日志和恢复前后的查询结果。

[`docs/`](docs/) 保存旧版技术交接和交付资料。现有内核的构建与运行使用本页命令。
