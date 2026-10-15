"""Write the packaged list of global names readable without declaration (lint77-globals.json).

The list is the result of the native `u-survey` probe (probe_rules77.py): every platform
name compiled as `Х77 = <Имя>;` through 1C++ `ВыполняемыйМодуль` on the pinned stand.
It is a property of that stand's configuration, so the file records its provenance.

  python research/rules77/export_globals77.py .artifacts/stage5-rule-probes-YYYYMMDD-globals.json
      src/harness77/lint77-globals.json
"""

import hashlib
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    evidence_path, output = map(Path, (argv or sys.argv[1:]))
    data = evidence_path.read_bytes()
    evidence = json.loads(data)
    case = next(c for c in evidence["cases"] if c["id"] == "u-survey")
    if case["verdict"] != "confirmed" or not case["observed"]["value"].startswith("total="):
        raise SystemExit("u-survey did not complete")
    total, *names = case["observed"]["value"].split(";")
    if os.path.lexists(output):
        raise SystemExit(f"output exists: {output}")
    result = {
        "description": "Имена платформы 1С 7.7, которые модуль читает без объявления (глобальный контекст). "
                       "Установлено пробой: каждое имя каталога скомпилировано как «Х = <Имя>;».",
        "provenance": {"evidence": evidence_path.name, "evidence_sha256": hashlib.sha256(data).hexdigest(),
                       "run_id": case["run_id"], "stand": evidence["stand"], "generated": evidence["generated"],
                       "candidates": int(total.split("=", 1)[1])},
        "limitations": ["Набор относится к конфигурации стенда: в конфигурациях с другими компонентами "
                        "возможны дополнительные глобальные имена (--allow).",
                        "Контекст формы (Форма и др.) берётся из каталога, а не из этой пробы."],
        "names": names,
    }
    with open(output, "x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=1)
        stream.write("\n")


if __name__ == "__main__":
    main()
