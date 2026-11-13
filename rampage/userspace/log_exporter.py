import sys
import re
import argparse
from prometheus_client import start_http_server, Counter, Gauge

kernel_warning_counter = Counter(
    'kernel_warning',
    'Kernel warning information',
    ['pfn', 'warning_type']
)

num_tested_gauge = Gauge('num_tested', 'Number of tested frames')

def process_line(line):
    """
    解析单行日志并更新指标
    """
    line = line.strip()
    if not line:
        return

    bad_frame_match = re.search(r"pfn ([0-9a-fA-F]+)", line)
    if "bad frame" in line and bad_frame_match:
        pfn_value = bad_frame_match.group(1)

        kernel_warning_counter.labels(
            pfn=pfn_value, 
            warning_type="bad frame"
        ).inc()
        return

    tested_match = re.search(r"Tested (\d+) frames", line)
    if tested_match:
        tested_count = int(tested_match.group(1))

        num_tested_gauge.set(tested_count)
        return

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000, help="Port to expose metrics")
    args = parser.parse_args()

    print(f"Starting Prometheus exporter on port {args.port}...")
    start_http_server(args.port)

    print("Listening on stdin (Pipe mode)...")

    try:

        for line in sys.stdin:
            process_line(line)

    except KeyboardInterrupt:
        print("\nStopping exporter...")
    except Exception as e:
        print(f"Error: {e}")
