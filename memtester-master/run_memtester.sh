#!/bin/bash

MEMTESTER=./memtester
LOOPS=1

echo "=============================="
echo "       memtester 错误注入"
echo "=============================="

# 输入内存大小
echo ""
read -p "请输入测试内存大小（例如 256M、1G、512K）: " MEM_SIZE

# 输入注入页号
echo ""
read -p "请输入要注入错误的页号（相对 bufa 起始页，输入 -1 表示不注入）: " inject_page

# 选择注入类型
echo ""
echo "请选择错误注入类型："
echo "  0 - 不注入错误"
echo "  1 - Stuck Address   : 地址线断路/短路、地址译码器故障"
echo "  2 - Compare XOR     : 存储单元间耦合干扰、位间交叉干扰"
echo "  3 - Solid Bits      : 位粘连故障（stuck-at-0 或 stuck-at-1）"
echo "  4 - Checkerboard    : 相邻单元/位线间的电气耦合与串扰"
echo "  5 - Walking Zeroes  : 数据线短路、位间相互干扰"
echo "  6 - Compare OR      : 存储单元电荷保持能力不足、弱写故障、相邻单元漏电"
echo "  7 - 8-bit Writes    : 字节写入掩码逻辑故障、窄写操作对相邻字节的误写入"
echo ""
read -p "请输入类型编号 [0-7]: " inject_kind

# 构造命令
CMD="$MEMTESTER -i $inject_page -c $inject_kind $MEM_SIZE $LOOPS"
echo ""
echo "执行命令: $CMD"
echo "=============================="
$CMD
