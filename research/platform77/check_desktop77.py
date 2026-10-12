"""Launch only a tiny Python child to verify private desktop inheritance."""
import argparse
import ctypes as C
import json
from pathlib import Path
import sys

from desktop77 import DesktopProcess, PrivateDesktop, thread_desktop_name


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        api = C.WinDLL("kernel32")
        print(json.dumps({"desktop": thread_desktop_name(api.GetCurrentThreadId())}))
        return
    args.output.mkdir(parents=True, exist_ok=False)
    api = C.WinDLL("kernel32")
    original = thread_desktop_name(api.GetCurrentThreadId())
    with PrivateDesktop() as desktop:
        with (args.output / "child.json").open("wb") as stream:
            child = DesktopProcess([sys.executable, "-B", str(Path(__file__).resolve()), "--child"], desktop.name, stream)
            try:
                code = child.wait(10)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(5)
        actual = json.loads((args.output / "child.json").read_text(encoding="utf-8"))
        if code != 0 or actual["desktop"] != desktop.name:
            raise RuntimeError("child was not created on requested private desktop")
        result = {"requested": desktop.name, "child": actual["desktop"], "exit_code": code}
    after = thread_desktop_name(api.GetCurrentThreadId())
    if after != original:
        raise RuntimeError("controller desktop changed")
    result.update(controller_before=original, controller_after=after, private_desktop_closed=True)
    (args.output / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
