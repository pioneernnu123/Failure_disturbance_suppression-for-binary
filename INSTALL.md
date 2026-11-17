# 内存失效扰动抑制二进制安装手册

适用于 riscv64 服务器。包内驱动须与服务器现有内核匹配，解包后可直接运行。

## 一 解包并加载驱动

在压缩包所在目录执行。

```bash
tar -xzf Failure_disturbance_suppression-binary-riscv64.tar.gz
cd Failure_disturbance_suppression-binary-riscv64
sudo insmod ./modules/phys_mem.ko
```

## 二 运行检测和注入控制

窗口一在解包目录启动检测，记下程序打印的 `RUN_ID`。

```bash
sudo ./app/main.dist/rampage \
    -t memtester \
    --memtester-args="-i 5" \
    --memtester-inject-type=0 \
    -a slow \
    --frames-per-check=50 \
    --scan-mode=local \
    --max-memory=2G \
    --logfile=./memtester-slow.log \
    --memtester=./bin/memtester
```

窗口二从压缩包所在目录启动注入控制。

```bash
cd Failure_disturbance_suppression-binary-riscv64
sudo ./app/injection_control.dist/injection-control
```

先等窗口一以编号 `0` 完成一轮。窗口二输入 `1` 并回车，窗口一出现 `bad frame` 后，输入 `0` 停止注入。新编号从下一轮开始生效，直到再次切换。

编号 `1` 为地址固定，`2` 为异或比较，`3` 为固定位，`4` 为棋盘格，`5` 为游走零，`6` 为或运算比较，`7` 为八位写入。

测试结束时，在窗口一按 Ctrl+C 并等待退出，在窗口二输入 `q` 并回车。

## 三 四项自动验收

自动验收在解包目录单独运行。

```bash
sudo ./app/run_memory_test.dist/run-memory-test --memtester=./bin/memtester
```

四项通过结果依次为 `5/5`、`3/3`、`2/2`、`5/5`。程序会打印 `RUN_ID` 和结果目录。

## 四 取证和恢复

检测退出后，在解包目录执行。出现提示时，输入本次运行打印的 `RUN_ID` 数字并回车。

```bash
read -r -p '输入本次 RUN_ID：' RUN_ID
sudo ./app/phys_memctl.dist/phys_memctl status --run-id "$RUN_ID" | tee isolation-status.txt
```

核对 `已隔离` 记录中的 PFN 和偏移。取证完成后恢复本批次的模拟隔离页。

```bash
sudo ./app/phys_memctl.dist/phys_memctl restore --run-id "$RUN_ID" --simulated-only 2>&1 | tee restore.log
sudo ./app/phys_memctl.dist/phys_memctl status --run-id "$RUN_ID" | tee -a restore.log
```

恢复应显示 `failed=0`，随后查询应显示 `simulated=0`，对应记录变为 `已恢复`。来源不明的页继续隔离。
