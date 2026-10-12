"""Register only the installed V77L.Application (user scope by default).

An experiment helper, not an installer for 1C or its external components.
Defaults to inspection. --apply is an explicit registry mutation.
Existing registrations are never overwritten. Evidence records both views.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import uuid
import winreg


PROGID = "V77L.Application"
CLSID = "{63112D81-94F0-11D2-9F39-008048DA120F}"
VIEWS = [("Registry32", winreg.KEY_WOW64_32KEY), ("Registry64", winreg.KEY_WOW64_64KEY)]


def read_key(hive, path, view):
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
            values = {}
            for index in range(winreg.QueryInfoKey(key)[1]):
                name, value, kind = winreg.EnumValue(key, index)
                values[name] = {"value": value, "kind": kind}
            return values
    except FileNotFoundError:
        return None


def snapshot():
    rows = []
    for name, view in VIEWS:
        for path in [PROGID, PROGID + "\\CLSID", "CLSID\\" + CLSID,
                     "CLSID\\" + CLSID + "\\LocalServer32", "CLSID\\" + CLSID + "\\ProgID"]:
            rows.append({"view": name, "path": path,
                         "merged": read_key(winreg.HKEY_CLASSES_ROOT, path, view),
                         "user": read_key(winreg.HKEY_CURRENT_USER, "Software\\Classes\\" + path, view),
                         "machine": read_key(winreg.HKEY_LOCAL_MACHINE, "Software\\Classes\\" + path, view)})
    return rows


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--scope", choices=["user", "machine"], default="user")
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    binary = exe.read_bytes()
    prog_offset = binary.find(PROGID.encode("ascii") + b"\0")
    guid_offset = binary.find(uuid.UUID(CLSID).bytes_le)
    if prog_offset < 0 or not prog_offset < guid_offset < prog_offset + 64:
        raise SystemExit("Installed executable does not contain the expected adjacent ProgID/CLSID.")
    args.evidence.mkdir(parents=True, exist_ok=False)
    report = {"observed_at": datetime.datetime.now().astimezone().isoformat(),
              "exe": str(exe), "sha256": hashlib.sha256(binary).hexdigest(),
              "progid": PROGID, "clsid": CLSID, "prog_offset": prog_offset,
              "guid_offset": guid_offset, "scope": args.scope,
              "before": snapshot(), "applied": False}

    def save():
        (args.evidence / "registration.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    if args.apply:
        if any(row[args.scope] is not None for row in report["before"]):
            raise SystemExit("Registration already exists; refusing to overwrite it. See evidence.")
        values = {
            PROGID: {"": "1C:Enterprise 7.7 local OLE server"},
            PROGID + "\\CLSID": {"": CLSID},
            "CLSID\\" + CLSID: {"": "1C:Enterprise 7.7 local OLE server"},
            "CLSID\\" + CLSID + "\\ProgID": {"": PROGID},
            "CLSID\\" + CLSID + "\\LocalServer32": {"": '"' + str(exe) + '"', "ServerExecutable": str(exe)},
        }
        report["written"] = []
        try:
            for name, view in VIEWS:
                for path, entries in values.items():
                    hive = winreg.HKEY_CURRENT_USER if args.scope == "user" else winreg.HKEY_LOCAL_MACHINE
                    with winreg.CreateKeyEx(hive,
                                            "Software\\Classes\\" + path, 0,
                                            winreg.KEY_WRITE | view) as key:
                        for label, value in entries.items():
                            winreg.SetValueEx(key, label, 0, winreg.REG_SZ, value)
                    report["written"].append({"view": name, "path": path, "values": entries})
                    save()
            report["applied"] = True
        finally:
            report["after"] = snapshot()
            save()
    print(json.dumps({"applied": report["applied"], "evidence": str(args.evidence), "progid": PROGID}))


if __name__ == "__main__":
    main()
