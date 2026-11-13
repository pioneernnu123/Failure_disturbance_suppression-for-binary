# //LZU CHANGE
import os


DEFAULT_INJECTION_STATE_PATH = "/tmp/rampage_memtester_injection_type"
MIN_INJECTION_TYPE = 0
MAX_INJECTION_TYPE = 7

INJECTION_TYPE_NAMES = {
    0: "None",
    1: "Stuck Address",
    2: "Compare XOR",
    3: "Solid Bits",
    4: "Checkerboard",
    5: "Walking Zeroes",
    6: "Compare OR",
    7: "8-bit Writes",
}


def validate_injection_type(injection_type):
    injection_type = int(injection_type)
    if not MIN_INJECTION_TYPE <= injection_type <= MAX_INJECTION_TYPE:
        raise ValueError(
            "memtester injection type must be between %d and %d"
            % (MIN_INJECTION_TYPE, MAX_INJECTION_TYPE)
        )
    return injection_type


def read_injection_type(path=DEFAULT_INJECTION_STATE_PATH, default=0):
    try:
        with open(path, "r") as state_file:
            value = state_file.read().strip()
        return validate_injection_type(value)
    except (OSError, TypeError, ValueError):
        return validate_injection_type(default)


def write_injection_type(injection_type, path=DEFAULT_INJECTION_STATE_PATH):
    injection_type = validate_injection_type(injection_type)
    temporary_path = "%s.%d.tmp" % (path, os.getpid())

    try:
        with open(temporary_path, "w") as state_file:
            state_file.write("%d\n" % injection_type)
            state_file.flush()
            os.fsync(state_file.fileno())
        os.replace(temporary_path, path)
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass

    return injection_type
