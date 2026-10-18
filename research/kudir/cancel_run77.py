"""Cancel a running `harness77 run` the way a user does, after a delay (task 006, N5).

  python research/kudir/cancel_run77.py --after 180 -- --project ... --stand ... --output-root ...

The run starts in its own process group and receives Ctrl+Break (CTRL_BREAK_EVENT),
which `harness77 run` handles like Ctrl+C. Ctrl+C itself cannot be sent to another
process group on Windows; the owner's manual Ctrl+C in a console covers that path.
Prints the run's summary JSON and the seconds from the signal to the run's exit.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--after", type=float, required=True, help="seconds before the cancellation")
    parser.add_argument("run_arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    run_arguments = args.run_arguments[1:] if args.run_arguments[:1] == ["--"] else args.run_arguments
    process = subprocess.Popen([sys.executable, "-m", "harness77", "run", *run_arguments],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    started = time.monotonic()
    while process.poll() is None and time.monotonic() - started < args.after:
        time.sleep(0.5)
    sent = None
    if process.poll() is None:
        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        sent = time.monotonic()
    stdout, stderr = process.communicate()
    result = {"signal_after_s": round(sent - started, 1) if sent else None,
              "exit_after_signal_s": round(time.monotonic() - sent, 1) if sent else None,
              "exit_code": process.returncode}
    try:
        result["summary"] = json.loads(stdout.decode("utf-8"))
    except ValueError:
        result["stdout"], result["stderr"] = stdout.decode("utf-8", "replace")[-2000:], stderr.decode("utf-8", "replace")[-2000:]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
