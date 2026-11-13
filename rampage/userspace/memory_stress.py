import psutil
import time
import sys
import os

TARGET_PERCENT = 92.0  

CHUNK_SIZE = 100 * 1024 * 1024 

def occupy_memory():

    dummy_buffer = [] 

    print(f"[*] 开始执行内存施压程序...")
    print(f"[*] 目标占用率: {TARGET_PERCENT}%")
    print(f"[*] 按 Ctrl+C 可以随时释放内存并退出")
    print("-" * 40)

    try:
        while True:

            mem = psutil.virtual_memory()
            current_percent = mem.percent

            sys.stdout.write(f"\r[+] 当前内存占用: {current_percent}% | 已缓存块数: {len(dummy_buffer)}")
            sys.stdout.flush()

            if current_percent >= TARGET_PERCENT:
                print("\n\n[!] 已达到目标内存水位！")
                print(f"[*] 现在系统内存压力很大，请在另一个终端运行你的 auto_inject.py 进行测试。")
                print("[*] 正在保持内存占用 (按 Ctrl+C 结束)...")

                while True:
                    time.sleep(1)

            try:

                new_chunk = bytearray(CHUNK_SIZE)

                dummy_buffer.append(new_chunk)

                time.sleep(0.1) 
            except MemoryError:
                print("\n[!] 物理内存耗尽，无法申请更多内存！")
                break

    except KeyboardInterrupt:
        print("\n\n[*] 接收到停止指令，正在释放内存...")

        dummy_buffer = []
        print("[*] 内存已释放。程序退出。")

if __name__ == "__main__":
    occupy_memory()
