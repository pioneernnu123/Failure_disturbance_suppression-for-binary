# RAMpage 内存失效扰动抑制

当前代码使用外部模块在目标 RISC-V Linux 内核上分配测试页，memtester 直接测试
设备会话映射的页面，驱动在映射关闭后把报告异常的页转入模块级隔离表。
无需修改内核源码或打开 `CONFIG_MEMORY_FAILURE`。这与原 RAMpage 任意 PFN
扫描及 HWPoison 机制不同；原范围须另行评估。

在项目目录直接编译、测试、取证和按批次恢复的命令见
[仓库根目录说明](../README.md)。

`main.py` 持续测试驱动分配的页，`injection_control.py` 在另一窗口设置后续
调用的注入编号。`run_memory_test.py` 自动运行大纲的四项验收。两种运行方式
都会生成供 `phys_memctl` 查询和恢复的批次号。

RAMpage 的早期论文和原型背景：

* H. Schirmeier, J. Neuhalfen, I. Korb, O. Spinczyk, and M. Engel.
  [RAMpage: Graceful degradation management for memory errors in commodity
  Linux servers](https://ess.cs.tu-dortmund.de/~hsc/Publications/files/PRDC-FAST-2011-Schirmeier.pdf).
  In *Proceedings of the 17th IEEE Pacific Rim International Symposium on
  Dependable Computing (PRDC '11)*, pages 89-98, Pasadena, CA, USA, Dec. 2011.

* H. Schirmeier, I. Korb, O. Spinczyk, and M. Engel. [Efficient online memory
  error assessment and circumvention for Linux with
  RAMpage](https://ess.cs.tu-dortmund.de/~hsc/Publications/files/IJCCBS-2013-Schirmeier.pdf).
  *International Journal of Critical Computer-Based Systems*, 4(3):227-247,
  2013.
