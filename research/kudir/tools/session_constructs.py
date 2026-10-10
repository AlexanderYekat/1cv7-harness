import re, sys
sys.stdout.reconfigure(encoding="utf-8")
TOKEN = re.compile(r'"(?:[^"\n]|"")*"|//[^\n]*')
for p in sys.argv[1:]:
    lines = [TOKEN.sub(lambda m: '""' if m[0].startswith('"') else "", l) for l in open(p, encoding="utf-8-sig").read().splitlines()]
    issues = []
    kind = None; seen_stmt = False
    for i, l in enumerate(lines, 1):
        s = l.strip()
        m = re.match(r"(?i)(Функция|Процедура)\s+\w+\s*\(.*\)\s*(Экспорт)?\s*(далее)?\s*$", s)
        if m:
            if not m[3]:
                kind = m[1].lower(); seen_stmt = False
            continue
        if re.match(r"(?i)Конец(Функции|Процедуры)\b", s):
            kind = None; continue
        if re.search(r"(?i)\bДля\s+Каждого\b|\bНовый\s+\w|\bИначеЕсли\b.*\bИначе\s*Если\b|\bВыполнить\s*\(|\bЗначениеЗаполнено\s*\(|\bСтрНайти\s*\(|\bСтрРазделить\s*\(|\bСтрШаблон\s*\(|\bВозвратЗначения\b|\bТогда\s*;|\bКонецЕсли\s*;?\s*\bКонецЕсли\b", s):
            issues.append((i, "non-7.7 construct?", s[:100]))
        if kind:
            if re.match(r"(?i)Перем\s", s) and seen_stmt:
                issues.append((i, "local Перем after statements", s[:80]))
            elif s:
                seen_stmt = True
            for r in re.finditer(r"(?i)(?<![\w.])Возврат\b\s*([^;]*);", s):
                if kind == "функция" and not r[1].strip():
                    issues.append((i, "Возврат без значения в функции", s[:80]))
                if kind == "процедура" and r[1].strip():
                    issues.append((i, "Возврат со значением в процедуре", s[:80]))
    print(p, issues or "no issues")
