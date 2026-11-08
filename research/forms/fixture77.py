"""Prepare data once in a run's copy and verify after closing (tasks 024–035).

The snippets are ordinary trusted 1C test code, just like an ERT test module. The
adapter must require the run's verified configuration copy before executing them.
Journal mode prepares prerequisites; its document reference comes from a UI save.
"""

import re

KEYS = ("fixture_setup", "fixture_mode", "fixture_verify", "fixture_post", "fixture_operations", "journal_form")


def options(parameters, name):
    if not any(key in parameters for key in KEYS):
        return None
    setup = parameters.get("fixture_setup")
    mode = parameters.get("fixture_mode", "existing")
    verify = parameters.get("fixture_verify")
    if not isinstance(setup, str) or not setup.strip():
        raise ValueError("fixture_setup must be a non-empty 1C function body returning a reference")
    if mode not in ("existing", "owner", "journal", "journal_existing"):
        raise ValueError("fixture_mode must be existing, owner, journal or journal_existing")
    if mode in ("journal", "journal_existing"):
        import journal77
        journal77.validate(parameters, name)
    elif "journal_form" in parameters:
        raise ValueError("journal_form requires fixture_mode journal or journal_existing")
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
    post = parameters.get("fixture_post", False)
    if "fixture_post" in parameters and post is not True:
        raise ValueError("fixture_post must be true when specified")
    if post and (not document or mode != "existing" or verify is None):
        raise ValueError("fixture_post requires an existing document and fixture_verify")
    operations = parameters.get("fixture_operations", [])
    if "fixture_operations" in parameters:
        if post or not document or mode != "existing" or verify is None:
            raise ValueError("fixture_operations requires an existing document, fixture_verify and no fixture_post")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 20:
            raise ValueError("fixture_operations must contain 1 to 20 operations")
        ids = set()
        for step in operations:
            if not isinstance(step, dict) or set(step) - {"id", "action", "before"}:
                raise ValueError("invalid fixture operation fields")
            id_ = step.get("id")
            if not isinstance(id_, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,23}", id_) or id_ in ids:
                raise ValueError("fixture operation needs a unique short ASCII id")
            ids.add(id_)
            if step.get("action") not in ("post", "unpost"):
                raise ValueError("fixture operation action must be post or unpost")
            before = step.get("before", "")
            if not isinstance(before, str) or "\0" in before:
                raise ValueError("fixture operation before must be 1C code without NUL")
            before.encode("cp1251")
    return {"setup": setup, "verify": verify, "mode": mode, "post": post, "operations": operations,
            "journal": parameters.get("journal_form")}


def commands(settings):
    if not settings:
        return []
    result = ["post"] if settings["post"] else []
    for step in settings.get("operations", []):
        result += [step["action"] + "-" + step["id"], "verify-" + step["id"]]
    return result + (["verify"] if settings["verify"] is not None else [])


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
    if settings["mode"] in ("journal", "journal_existing"):
        parts = settings["journal"].split(".")
        return f'"Журнал.{parts[1]}.{parts[3]}", Контекст77'
    if settings["mode"] == "existing":
        return "Объект77Данных, Контекст77, 0"
    parts = name.split(".")
    group = int(parts[-1].casefold() == "формагруппы")
    return f'"Элемент.{parts[1]}", Контекст77, , {group}, Объект77Данных'


def controller(text, settings, expected):
    """Insert setup ahead of check/open and a separate verification command after result."""
    if settings["mode"] == "journal":
        import journal77
        return journal77.controller(text, settings, expected)
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
    if settings["mode"] == "journal_existing":
        prefix = prefix.replace('            Ошибка77Данных = Harness77ТипДанных(Объект77Данных);',
                                '''            Ошибка77Данных = Harness77ТипДанных(Объект77Данных);
            Если Ошибка77Данных = "" Тогда
                Ответ77 = Ответ77 + "fixture-initial:" + Harness77ПроверитьДанные(Объект77Данных) + РазделительСтрок;
            КонецЕсли;''')
    postings = ([{"action": "post", "command": "post"}] if settings.get("post") else []) + [
        dict(step, command=step["action"] + "-" + step["id"]) for step in settings.get("operations", [])]
    for step in postings:
        branch_text = '''    ИначеЕсли Команда = "__COMMAND__" Тогда
        Попытка
            Док77Проведения = СоздатьОбъект("Документ." + Объект77Данных.Вид());
            Если Док77Проведения.НайтиДокумент(Объект77Данных) <> 1 Тогда
                Ответ77 = Ответ77 + "post-error:prepared document not found" + РазделительСтрок;
            Иначе
                __BEFORE__
                Результат77Проведения = Док77Проведения.__METHOD__;
                Ответ77 = Ответ77 + "post-return:" + Строка(Результат77Проведения) + РазделительСтрок;
                // Read persisted state through a new object, not the posting object's cached state.
                Док77Проверки = СоздатьОбъект("Документ." + Объект77Данных.Вид());
                Если Док77Проверки.НайтиДокумент(Объект77Данных) <> 1 Тогда
                    Ответ77 = Ответ77 + "post-error:posted document not found" + РазделительСтрок;
                Иначе
                    Ответ77 = Ответ77 + "post-posted:" + Строка(Док77Проверки.Проведен()) + РазделительСтрок;
                КонецЕсли;
            КонецЕсли;
        Исключение
            Ответ77 = Ответ77 + "post-error:" + ОписаниеОшибки() + РазделительСтрок;
        КонецПопытки;
'''
        prefix += branch_text.replace("__COMMAND__", step["command"]).replace(
            "__BEFORE__", step.get("before", "")).replace("__METHOD__", "Провести(1)" if step["action"] == "post"
                                                        else "СделатьНеПроведенным()")
    if settings["verify"] is not None:
        verify_commands = ["verify"] + ["verify-" + step["id"] for step in settings.get("operations", [])]
        condition = " ИЛИ ".join('(Команда = ' + literal(cmd) + ')' for cmd in verify_commands)
        prefix += '''    ИначеЕсли __VERIFY__ Тогда
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
'''.replace("__VERIFY__", condition)
    branch = '    Если (Команда = "check") ИЛИ (Команда = "open") Тогда'
    if text.count(branch) != 1 or text.count("Функция Harness77Ert(") != 1:
        raise ValueError("unexpected form controller layout for fixtures")
    return (("Перем Объект77Подготовки, Объект77Источник, Дата77Копии, Номер77Копии;\n" if settings["mode"] == "journal_existing" else "")
            + "Перем Объект77Данных, Попытка77Данных, Ошибка77Данных;\n" + text.replace(
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
    if command == "post" or command.startswith(("post-", "unpost-")):
        returned = [line[12:].strip() for line in lines if line.startswith("post-return:")]
        posted = [line[12:].strip() for line in lines if line.startswith("post-posted:")]
        errors = [line[len("post-error:"):] for line in lines if line.startswith("post-error:")]
        valid = len(returned) == len(posted) == 1 and returned[0] in ("0", "1") and posted[0] in ("0", "1")
        known = all(line.startswith(("selected:", "post-return:", "post-posted:", "post-error:")) for line in lines)
        row["posting"] = {"returned": int(returned[0]) if len(returned) == 1 and returned[0] in ("0", "1") else None,
                          "posted": int(posted[0]) if len(posted) == 1 and posted[0] in ("0", "1") else None,
                          "errors": errors}
        if valid:
            row["value"] = returned[0] + "|" + posted[0]
        if known and (errors or row["diagnostics"]):
            row["status"] = "failed"
        elif not valid or not known:
            row["status"] = "blocked"
            return True, "fixture_post_protocol_invalid: missing or malformed posting result"
        else:
            row["status"] = "passed" if returned == ["1"] and posted == (["0"] if command.startswith("unpost-") else ["1"]) else "failed"
        return True, None
    if command == "verify" or command.startswith("verify-"):
        values = [line[len("fixture-value:"):] for line in lines if line.startswith("fixture-value:")]
        valid = len(values) == 1 and not row["diagnostics"] and all(
            line.startswith(("selected:", "fixture-value:")) for line in lines)
        row.update(status="passed" if valid else "failed",
                   value=values[0] if len(values) == 1 else None)
        return True, None
    return False, None
