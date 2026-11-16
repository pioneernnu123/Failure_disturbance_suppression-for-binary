# 内存失效扰动抑制二进制安装手册

适用于 riscv64 服务器。使用与服务器现有内核兼容的包内驱动。解包后直接运行。

## 一 解包并加载驱动

```bash
tar -xzf Failure_disturbance_suppression-binary-riscv64.tar.gz
cd Failure_disturbance_suppression-binary-riscv64
sudo insmod ./modules/phys_mem.ko
```

## 二 运行检测和注入控制

窗口一在解包目录启动检测。

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

窗口二进入同一个解包目录，启动注入控制。

```bash
cd Failure_disturbance_suppression-binary-riscv64
sudo ./app/injection_control.dist/injection-control
```

输入 `0～7` 并回车。下一次 memtester 调用开始使用该编号，直到输入新编号。`0` 表示无注入，`1` 表示地址固定错误。测试结束后，窗口一按 Ctrl+C，等当前检测完成并退出。窗口二输入 `q` 并回车。

## 三 四项自动验收

需要自动执行四项用例时，在解包目录单独运行。

```bash
sudo ./app/run_memory_test.dist/run-memory-test --memtester=./bin/memtester
```

四项通过结果依次为 `5/5`、`3/3`、`2/2`、`5/5`。程序打印批次号和结果目录。

## 四 取证和恢复

检测退出后，输入本次运行输出的 `RUN_ID` 数字，保存隔离记录。

```bash
read -r -p '输入实际 RUN_ID: ' RUN_ID
sudo ./app/phys_memctl.dist/phys_memctl status --run-id "$RUN_ID" | tee isolation-status.txt
```

取证完成后，恢复同批次的模拟隔离页。

```bash
sudo ./app/phys_memctl.dist/phys_memctl restore --run-id "$RUN_ID" --simulated-only 2>&1 | tee restore.log
sudo ./app/phys_memctl.dist/phys_memctl status --run-id "$RUN_ID" | tee -a restore.log
```

恢复应显示 `failed=0`，随后查询应显示 `simulated=0`。来源不明的页继续隔离。
