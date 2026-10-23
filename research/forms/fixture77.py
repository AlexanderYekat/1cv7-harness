"""Task 024: prepare data once in a run's copy, open its reference, verify after closing.

The snippets are ordinary trusted 1C test code, just like an ERT test module. The
adapter must require the run's verified configuration copy before executing them.
"""

KEYS = ("fixture_setup", "fixture_mode", "fixture_verify")


def options(parameters, name):
    if not any(key in parameters for key in KEYS):
        return None
    setup = parameters.get("fixture_setup")
    mode = parameters.get("fixture_mode", "existing")
    verify = parameters.get("fixture_verify")
    if not isinstance(setup, str) or not setup.strip():
        raise ValueError("fixture_setup must be a non-empty 1C function body returning a reference")
    if mode not in ("existing", "owner"):
        raise ValueError("fixture_mode must be existing or owner")
    if verify is not None and (not isinstance(verify, str) or not verify.strip()):
        raise ValueError("fixture_verify must be a non-empty 1C function body returning a string")
    for code in (setup, verify):
        if code is not None:
            code.encode("cp1251")
            if "\0" in code:
                raise ValueError("fixture code contains NUL")
    parts = (name or "").casefold().split(".")
    catalog = len(parts) == 3 and parts[0] == "справочник" and parts[2] in ("формаэлемента", "формагруппы")
    document = len(parts) == 2 and parts[0] == "документ"
    if not (catalog or document) or (mode == "owner" and not catalog):
        raise ValueError("fixtures require an object form; owner mode requires a catalog object form")
    return {"setup": setup, "verify": verify, "mode": mode}


def context(name, settings, metadata):
    """Expected runtime reference type/kind/group; metadata is that of the verified copy."""
    parts = name.split(".")
    if settings["mode"] == "owner":
        owner = metadata.catalog(parts[1])["owner"]
        if not owner:
            raise ValueError(f"{name}: fixture_mode owner requires a subordinate catalog")
        return {"type": "Справочник", "kind": owner, "group": 0}
    return {"type": "Документ" if parts[0].casefold() == "документ" else "Справочник",
            "kind": parts[1], "group": int(parts[-1].casefold() == "формагруппы")}


def open_arguments(name, settings):
    if settings["mode"] == "existing":
        return "Объект77Данных, Контекст77, 0"
    parts = name.split(".")
    group = int(parts[-1].casefold() == "формагруппы")
    return f'"Элемент.{parts[1]}", Контекст77, , {group}, Объект77Данных'


def controller(text, settings, expected):
    """Insert setup ahead of check/open and a separate verification command after result."""
    literal = lambda value: '"' + value.replace('"', '""') + '"'
    checks = f'''    Если ТипЗначенияСтр(Объект77) <> {literal(expected["type"])} Тогда
        Возврат "reference type does not match form_object";
    КонецЕсли;
    Если ВРег(Объект77.Вид()) <> ВРег({literal(expected["kind"])}) Тогда
        Возврат "reference kind does not match form_object or its owner";
    КонецЕсли;
    Если Объект77.Выбран() <> 1 Тогда
        Возврат "fixture returned an empty or unwritten reference";
    КонецЕсли;
'''
    if expected["type"] == "Справочник":
        checks += f'''    Если Объект77.ЭтоГруппа() <> {expected["group"]} Тогда
        Возврат "reference group flag does not match form_object or its owner";
    КонецЕсли;
'''
    helpers = ("Функция Harness77ПодготовитьДанные()\n" + settings["setup"] + "\nКонецФункции\n\n"
               + "Функция Harness77ТипДанных(Объект77)\n" + checks + '    Возврат "";\nКонецФункции\n\n')
    if settings["verify"] is not None:
        helpers += ("Функция Harness77ПроверитьДанные(Объект77)\n" + settings["verify"]
                    + "\nКонецФункции\n\n")
    prefix = '''    Если Попытка77Данных = 0 Тогда
        Попытка77Данных = 1;
        Попытка
            Объект77Данных = Harness77ПодготовитьДанные();
            Ошибка77Данных = Harness77ТипДанных(Объект77Данных);
        Исключение
            Ошибка77Данных = ОписаниеОшибки();
        КонецПопытки;
    КонецЕсли;
    Если Ошибка77Данных <> "" Тогда
        Ответ77 = Ответ77 + "fixture-error:" + Ошибка77Данных + РазделительСтрок;
'''
    if settings["verify"] is not None:
        prefix += '''    ИначеЕсли Команда = "verify" Тогда
        Попытка
            Итог77Данных = Harness77ПроверитьДанные(Объект77Данных);
            Если ТипЗначенияСтр(Итог77Данных) = "Строка" Тогда
                Ответ77 = Ответ77 + "fixture-value:" + Итог77Данных + РазделительСтрок;
            Иначе
                Ответ77 = Ответ77 + "fixture-verify-error:verification must return a string" + РазделительСтрок;
            КонецЕсли;
        Исключение
            Ответ77 = Ответ77 + "fixture-verify-error:" + ОписаниеОшибки() + РазделительСтрок;
        КонецПопытки;
'''
    branch = '    Если (Команда = "check") ИЛИ (Команда = "open") Тогда'
    if text.count(branch) != 1 or text.count("Функция Harness77Ert(") != 1:
        raise ValueError("unexpected form controller layout for fixtures")
    return ("Перем Объект77Данных, Попытка77Данных, Ошибка77Данных;\n" + text.replace(
        "Функция Harness77Ert(", helpers + "Функция Harness77Ert(").replace(
            branch, prefix + branch.replace("    Если", "    ИначеЕсли", 1))
            + '\nПопытка77Данных = 0; Ошибка77Данных = "";\n')


def operation(command, lines, row):
    """Handle fixture errors/verification ahead of ordinary form protocol checks."""
    errors = [line for line in lines if line.startswith(("fixture-error:", "fixture-verify-error:"))]
    if errors:
        row.update(status="blocked" if errors[0].startswith("fixture-error:") else "failed",
                   fixture_errors=errors)
        return True, "fixture_setup_failed: " + errors[0] if row["status"] == "blocked" else None
    if command == "verify":
        values = [line[len("fixture-value:"):] for line in lines if line.startswith("fixture-value:")]
        valid = len(values) == 1 and not row["diagnostics"] and all(
            line.startswith(("selected:", "fixture-value:")) for line in lines)
        row.update(status="passed" if valid else "failed",
                   value=values[0] if len(values) == 1 else None)
        return True, None
    return False, None
