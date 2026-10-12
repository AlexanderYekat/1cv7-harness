"""Inspect/register this base's installed 32-bit 1CPP, without loading its DLL.

The values below match its embedded ATL registration resource. No existing
machine keys are overwritten. --apply requires an administrator token.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import winreg

from register_ole77_user import read_key


CLSID = "{FDE5AE76-00B3-4bdb-921B-D5937997B1B7}"


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    dll = args.dll.resolve(strict=True)
    binary = dll.read_bytes()
    start = binary.find(b"HKCR\r\n{")
    if start < 0:
        raise SystemExit("Expected ATL registration resource missing")
    resource = binary[start:binary.index(b"\0", start)].decode("ascii")
    for token in ["Addin.1C++.1", "Addin.1C++", CLSID, "InprocServer32", "ThreadingModel", "both"]:
        if token not in resource:
            raise SystemExit("Unexpected ATL resource; refusing registration")
    # PE machine must be i386; never register this DLL in the 64-bit view.
    pe = int.from_bytes(binary[0x3C:0x40], "little")
    if binary[pe:pe + 6] != b"PE\0\0\x4c\x01":
        raise SystemExit("Expected a 32-bit x86 DLL")
    root = "CLSID\\" + CLSID
    entries = {
        "Addin.1C++": {"": "OXY"},
        "Addin.1C++\\CLSID": {"": CLSID},
        "Addin.1C++.1": {"": "OXY"},
        "Addin.1C++.1\\CLSID": {"": CLSID},
        root: {"": "OXY"},
        root + "\\ProgID": {"": "Addin.1C++.1"},
        root + "\\VersionIndependentProgID": {"": "Addin.1C++"},
        root + "\\InprocServer32": {"": str(dll), "ThreadingModel": "both"},
    }

    def snapshot():
        return [{"path": path,
                 "user": read_key(winreg.HKEY_CURRENT_USER, "Software\\Classes\\" + path, winreg.KEY_WOW64_32KEY),
                 "machine": read_key(winreg.HKEY_LOCAL_MACHINE, "Software\\Classes\\" + path, winreg.KEY_WOW64_32KEY)}
                for path in entries]

    args.evidence.mkdir(parents=True, exist_ok=False)
    report = {"at": datetime.datetime.now().astimezone().isoformat(),
              "dll": str(dll), "sha256": hashlib.sha256(binary).hexdigest(),
              "resource": resource, "view": "Registry32", "before": snapshot(),
              "written": [], "applied": False}

    def save():
        (args.evidence / "registration.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    if args.apply:
        if any(row["machine"] is not None for row in report["before"]):
            raise SystemExit("Machine registration exists; refusing to overwrite")
        try:
            for path, values in entries.items():
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, "Software\\Classes\\" + path,
                                       0, winreg.KEY_WRITE | winreg.KEY_WOW64_32KEY) as key:
                    for name, value in values.items():
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                report["written"].append({"path": path, "values": values})
                save()
            report["applied"] = True
        finally:
            report["after"] = snapshot()
            save()
    print(json.dumps({"applied": report["applied"], "evidence": str(args.evidence)}))


if __name__ == "__main__":
    main()
