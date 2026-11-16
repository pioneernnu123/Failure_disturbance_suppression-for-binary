import psutil
import subprocess
import os
import sys
import time

MIN_AVAILABLE_MEM_MB = 1024  

MAX_MEM_PERCENT = 85.0

WORK_DIR = os.path.dirname(os.path.abspath(__file__))

INJECTION_CMD = [
    "sudo", "python3", "main.py",
    "-t", "memtester",
    "--memtester-args", "-i 5",
    "-a", "slow",
    "--frames-per-check", "50",
    "--logfile=" + os.path.join(WORK_DIR, "memtester-slow.log")
]

def check_memory_status():
    """
    检查当前内存状态
    返回: (is_safe, message)
    """
    mem = psutil.virtual_memory()

    available_mb = mem.available / (1024 * 1024)
    percent = mem.percent

    print(f"[-] 当前内存状态: 已用 {percent}% | 可用 {available_mb:.2f} MB")

    if percent > MAX_MEM_PERCENT:
        return False, f"内存占用过高 ({percent}%)，容易触发 OOM，建议清理内存后重试。"

    if available_mb < MIN_AVAILABLE_MEM_MB:
        return False, f"可用内存不足 ({available_mb:.2f} MB < {MIN_AVAILABLE_MEM_MB} MB)，工具可能无法分配所需 buffer。"

    return True, "内存状态良好，准备执行注入。"

def run_injection():

    try:
        print(f"[*] 正在切换工作目录到: {WORK_DIR}")
        os.chdir(WORK_DIR)
    except FileNotFoundError:
        print(f"[!] 错误: 找不到目录 {WORK_DIR}，请检查路径。")
        sys.exit(1)

    print(f"[*] 执行注入命令: {' '.join(INJECTION_CMD)}")
    print("[*] ---------------- STARTING INJECTION ----------------")

    try:

        subprocess.run(INJECTION_CMD, check=True)
        print("[*] ---------------- INJECTION FINISHED ----------------")
        print("[+] 注入流程结束，请检查日志验证检测机制是否生效。")
    except subprocess.CalledProcessError as e:
        print(f"[!] 注入命令执行出错，退出码: {e.returncode}")
    except KeyboardInterrupt:
        print("\n[!] 用户手动中止测试。")

if __name__ == "__main__":
    print("=== 内存错误注入前置环境检测脚本 ===")

    is_safe, msg = check_memory_status()

    if is_safe:
        print(f"[+] {msg}")

        time.sleep(1)

        run_injection()
    else:
        print(f"[!] {msg}")
        print("[!] 测试已取消，以保护系统稳定性。")
        sys.exit(1)
