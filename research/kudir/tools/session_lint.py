"""Static lint of a 1C 7.7 module text (review aid, NOT a compiler).

Usage: python -I lint77.py <module.txt> <dialog_ids_comma_separated>
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
src = Path(sys.argv[1]).read_bytes().decode("utf-8-sig")
dialog_ids = {x for x in sys.argv[2].split(",") if x}
W = r"A-Za-zА-Яа-яЁё_0-9"
STR = re.compile(r'"(?:[^"\n]|"")*"')
COM = re.compile(r"//[^\n]*")
code_lines = [COM.sub("", STR.sub('""', l)) for l in src.splitlines()]

KEYWORDS = {k.lower() for k in """Если Тогда ИначеЕсли Иначе КонецЕсли Пока Цикл КонецЦикла Для По Попытка Исключение
КонецПопытки ВызватьИсключение Возврат Продолжить Прервать Перейти И Или Не Знач Перем Функция Процедура КонецФункции
КонецПроцедуры Далее Экспорт Контекст""".split()}
# 1C 7.7 global-context functions/attributes (Russian + English aliases). Using one as a variable or
# formal parameter breaks compilation ("Ожидается имя формального параметра" / "Ожидается символ '('").
BUILTINS = {k.lower() for k in """
Мин Макс Окр Цел Лог Лог10 Число Строка Дата Пропись Формат Шаблон ФиксШаблон
СтрДлина ПустаяСтрока ВРег НРег Лев Прав Сред СокрЛ СокрП СокрЛП Найти СтрЗаменить СтрЧислоВхождений
СтрКоличествоСтрок СтрПолучитьСтроку Симв КодСимв ОемВАнси АнсиВОем РазделительСтрок РазделительСтраниц
РабочаяДата ТекущаяДата ДобавитьМесяц НачМесяца КонМесяца НачКвартала КонКвартала НачГода КонГода НачНедели КонНедели
ДатаГод ДатаМесяц ДатаЧисло НомерНеделиГода НомерДняГода НомерДняНедели ПериодСтр НачалоСтандартногоИнтервала
КонецСтандартногоИнтервала ТекущееВремя
ВвестиЗначение ВвестиЧисло ВвестиСтроку ВвестиДату ВвестиПериод ВвестиПеречисление Вопрос Предупреждение Сообщить
ОчиститьОкноСообщений Состояние Сигнал ОписаниеОшибки ОбработкаПрерыванияПользователя
ЗаголовокСистемы ИмяКомпьютера ИмяПользователя ПолноеИмяПользователя ПравоДоступа МонопольныйРежим ОсновнойЯзык
НачатьТранзакцию ЗафиксироватьТранзакцию ОтменитьТранзакцию ЗначениеВСтрокуВнутр ЗначениеИзСтрокиВнутр
ЗначениеВСтроку ЗначениеИзСтроки ЗначениеВФайл ЗначениеИзФайла СохранитьЗначение ВосстановитьЗначение
ТипЗначения ТипЗначенияСтр ПустоеЗначение ПолучитьПустоеЗначение НазначитьВид ЗаписьЖурналаРегистрации
КаталогПрограммы КаталогИБ КаталогПользователя КаталогВременныхФайлов ИспользуемоеИмяФайла СоздатьОбъект
ОткрытьФорму ОткрытьФормуМодально СтатусВозврата ЗапуститьПриложение КомандаСистемы ЗавершитьРаботуСистемы
НайтиПомеченныеНаУдаление НайтиСсылки УдалитьОбъекты ОбработкаОжидания ПрефиксАвтоНумерации Метаданные Константа
Перечисление ФС ВидыСубконто ПланыСчетов ОсновнойПланСчетов СчетПоКоду СформироватьПозициюДокумента
БухИтоги Операция Проводка ЗаписьЖурналаРегистрации РаскрытьИтоги
Min Max Round Int Log Log10 Number String Date Spelling Format Template FixTemplate StrLen IsBlankString Upper Lower
Left Right Mid TrimL TrimR TrimAll Find StrReplace StrCountOccur StrLineCount StrGetLine Chr Asc OemToAnsi AnsiToOem
WorkingDate CurDate AddMonth BegOfMonth EndOfMonth BegOfQuart EndOfQuart BegOfYear EndOfYear BegOfWeek EndOfWeek
GetYear GetMonth GetDay CurrentTime Message Status DoMessageBox DoQueryBox CreateObject ValueToStringInternal
ValueFromStringInternal ValueToString ValueFromString ValueType ValueTypeStr EmptyValue GetEmptyValue
""".split()}
# Names legitimately used here as values without "(": allowed only as members of BUILTINS read in expressions.

HDR = re.compile(r"^\s*(Функция|Процедура)\s+([" + W + r"]+)\s*\((.*?)\)\s*(Экспорт)?\s*(далее)?\s*$", re.I)
defs, fwd = {}, {}
for i, l in enumerate(code_lines):
    m = HDR.match(l)
    if not m:
        continue
    kind, name, params, _, is_fwd = m.groups()
    norm = re.sub(r"\s+", " ", params.strip())
    plist = [re.sub(r"(?i)^знач\s+", "", p.strip()).split("=")[0].strip() for p in norm.split(",") if p.strip()]
    entry = {"line": i + 1, "kind": kind.lower(), "params": norm, "plist": plist}
    if is_fwd:
        fwd[name] = entry
    else:
        end_kw = "конецфункции" if kind.lower() == "функция" else "конецпроцедуры"
        j = next(k for k in range(i + 1, len(code_lines)) if code_lines[k].strip().lower().startswith(end_kw))
        entry["end"] = j + 1
        defs[name] = entry

res = {"routines": len(defs), "forward": len(fwd)}
res["forward_without_body"] = sorted(set(fwd) - set(defs))
res["forward_signature_mismatch"] = [n for n in fwd if n in defs and (
    fwd[n]["params"].lower() != defs[n]["params"].lower() or fwd[n]["kind"] != defs[n]["kind"])]

module_vars = {}
first_def = min(d["line"] for d in list(defs.values()) + list(fwd.values()))
for i, l in enumerate(code_lines[:first_def - 1]):
    for v in re.findall(r"(?i)^\s*Перем\s+(.+?);", l):
        for x in v.split(","):
            module_vars[x.strip().split("[")[0].strip()] = i + 1
last_end = max(d["end"] for d in defs.values())
res["module_main_program_lines"] = [i + 1 for i in range(last_end, len(code_lines)) if code_lines[i].strip()]

# 1. Builtin / keyword names used as params, Перем, assignment targets, loop counters.
clash = []
for n, d in list(defs.items()) + [(k + " (далее)", v) for k, v in fwd.items()]:
    for p in d["plist"]:
        if p.lower() in BUILTINS or p.lower() in KEYWORDS:
            clash.append({"line": d["line"], "routine": n, "param": p})
for v, ln in module_vars.items():
    if v.lower() in BUILTINS or v.lower() in KEYWORDS:
        clash.append({"line": ln, "module_var": v})
for i, l in enumerate(code_lines):
    for v in re.findall(r"(?:^|;)\s*([" + W + r"]+)\s*=(?!=)", l):
        if v.lower() in BUILTINS:
            clash.append({"line": i + 1, "assign": v})
    for v in re.findall(r"(?i)\bДля\s+([" + W + r"]+)\s*=", l):
        if v.lower() in BUILTINS:
            clash.append({"line": i + 1, "for": v})
# Builtin function names read without "(" (e.g. "Строка + ...").
for i, l in enumerate(code_lines):
    if HDR.match(l):
        continue
    for m in re.finditer(r"(?<![\." + W + r"])([" + W + r"]+)(?![" + W + r"])", l):
        name = m.group(1)
        rest = l[m.end():].lstrip()
        if name.lower() in {"строка", "число", "дата"} and not rest.startswith("("):
            clash.append({"line": i + 1, "bare_builtin": name})
res["builtin_name_clash"] = clash

# 2. Calls before definition without forward.
order = []
for i, l in enumerate(code_lines):
    if HDR.match(l):
        continue
    for name in re.findall(r"(?<![\." + W + r"])([" + W + r"]+)\s*\(", l):
        if name in defs and name not in fwd and i + 1 < defs[name]["line"]:
            order.append({"line": i + 1, "name": name, "defined": defs[name]["line"]})
res["call_before_definition_without_forward"] = order

# 3. Arg count vs. params for local routines.
full = "\n".join(code_lines)
starts = [0]
for l in code_lines:
    starts.append(starts[-1] + len(l) + 1)


def line_of(pos):
    import bisect
    return bisect.bisect_right(starts, pos)


def split_args(s, start):
    depth, args, cur = 0, [], ""
    for i in range(start, len(s)):
        c = s[i]
        if c == "(":
            depth += 1
            if depth > 1:
                cur += c
        elif c == ")":
            depth -= 1
            if depth == 0:
                args.append(cur)
                return args
            cur += c
        elif c == "," and depth == 1:
            args.append(cur)
            cur = ""
        elif depth >= 1:
            cur += c
    return None


argc = []
unknown_calls = {}
for m in re.finditer(r"(?<![\." + W + r"])([" + W + r"]+)\s*\(", full):
    name = m.group(1)
    ln = line_of(m.start())
    if HDR.match(code_lines[ln - 1]):
        continue
    if name.lower() in KEYWORDS:
        continue
    if name not in defs:
        if name.lower() not in BUILTINS:
            unknown_calls.setdefault(name, []).append(ln)
        continue
    args = split_args(full, m.end() - 1)
    if args is None:
        continue
    n = 0 if (len(args) == 1 and not args[0].strip()) else len(args)
    if n > len(defs[name]["plist"]):
        argc.append({"line": ln, "name": name, "actual": n, "formal": len(defs[name]["plist"])})
res["too_many_arguments"] = argc
res["calls_to_non_local_non_builtin"] = unknown_calls

# 4. Identifiers read before any textual assignment in the routine (1C 7.7 compiles in one pass).
undeclared = {}
for name, d in defs.items():
    params = set(d["plist"])
    body = code_lines[d["line"]:d["end"] - 1]
    known = set()
    local_perem = set()
    for k, l in enumerate(body):
        for v in re.findall(r"(?i)^\s*Перем\s+(.+?);", l):
            local_perem.update(x.strip().split("[")[0].strip() for x in v.split(","))
    for k, l in enumerate(body):
        ln = d["line"] + 1 + k
        targets = set(re.findall(r"(?:^|;)\s*([" + W + r"]+)\s*=(?!=)", l))
        targets |= set(re.findall(r"(?i)\bДля\s+([" + W + r"]+)\s*=", l))
        # On a line "X = expr", the right side is compiled before X becomes known.
        for m in re.finditer(r"(?<![\." + W + r"])([A-Za-zА-Яа-яЁё_][" + W + r"]*)(?![" + W + r"])", l):
            ident = m.group(1)
            after = l[m.end():].lstrip()
            low = ident.lower()
            if low in KEYWORDS or low in BUILTINS or ident in params or ident in module_vars or ident in dialog_ids:
                continue
            if ident in defs or ident in fwd or ident in local_perem or ident in known:
                continue
            if ident in targets and re.match(r"=(?!=)", after):
                continue
            if after.startswith("("):
                continue  # reported as call
            if re.fullmatch(r"\d+", ident):
                continue
            undeclared.setdefault(name, []).append({"line": ln, "ident": ident})
        known |= targets
if undeclared:
    res["read_before_assignment_or_undeclared"] = undeclared
print(json.dumps(res, ensure_ascii=False, indent=1))
