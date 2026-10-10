"""Check global calls and method names of 1C 7.7 modules against the installed syntax helper (1cv7Lang.als)."""
import re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
als = Path(sys.argv[1]).read_bytes().decode("cp1251", "replace")
names = set()
for m in re.finditer(r'\{"Item","[^"]*","([^"]*)","([^"]*)"', als):
    for n in m.groups():
        n = re.sub(r"[^\wА-Яа-яЁё].*$", "", n.strip())
        if n:
            names.add(n.lower())
print("als names:", len(names))
TOKEN = re.compile(r'"(?:[^"\n]|"")*"|//[^\n]*')
for p in sys.argv[2:]:
    text = TOKEN.sub("", Path(p).read_text(encoding="utf-8-sig"))
    local = {m.lower() for m in re.findall(r"(?im)^\s*(?:Функция|Процедура)\s+(\w+)", text)}
    glob, meth = {}, {}
    for n, line in enumerate(text.splitlines(), 1):
        if re.match(r"(?i)\s*(Функция|Процедура)\s", line):
            continue
        for m in re.finditer(r"(\.)?\s*(\w+)\s*\(", line):
            name = m[2]
            if name.lower() in local | {"если", "пока", "и", "или", "не", "для", "возврат"}:
                continue
            if name.lower() in names:
                continue
            (meth if m[1] else glob).setdefault(name, []).append(n)
    print("==", p)
    print(" global calls not in 7.7 helper:", {k: v[:6] for k, v in glob.items()})
    print(" methods not in 7.7 helper:", {k: v[:6] for k, v in meth.items()})
