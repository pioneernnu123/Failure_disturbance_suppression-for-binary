#!/usr/bin/python3
# //LZU CHANGE

from optparse import OptionParser

from injection_state import (
    DEFAULT_INJECTION_STATE_PATH,
    INJECTION_TYPE_NAMES,
    write_injection_type,
)


def print_type_menu():
    print("错误类型：")
    for injection_type in sorted(INJECTION_TYPE_NAMES):
        print("  %d - %s" % (
            injection_type,
            INJECTION_TYPE_NAMES[injection_type],
        ))


def run_control_loop(state_path):
    print_type_menu()
    print("输入 0-7 可随时切换；输入 q 退出控制窗口。")

    while True:
        try:
            value = input("注入编号> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n控制窗口已退出。")
            return

        if value.lower() in ("q", "quit", "exit"):
            print("控制窗口已退出。")
            return

        try:
            injection_type = write_injection_type(value, state_path)
        except ValueError:
            print("请输入 0-7。")
            continue
        except OSError as error:
            print("写入状态文件失败：%s" % error)
            continue

        print("当前错误类型：%s" % INJECTION_TYPE_NAMES[injection_type])


if __name__ == "__main__":
    parser = OptionParser(usage="usage: %prog [options]")
    parser.add_option(
        "--state-file",
        dest="state_file",
        default=DEFAULT_INJECTION_STATE_PATH,
        metavar="PATH",
        help="shared injection type file [default: %default]",
    )
    (options, args) = parser.parse_args()
    if args:
        parser.error("No arguments supported!")

    run_control_loop(options.state_file)
