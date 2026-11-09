"""Tasks 034–035: create or find/open through a journal's native keyboard commands.

034 captures a newly saved reference; 035 compares every cursor reference with
the prepared saved target before Enter. Both bind a fresh owned document HWND.
"""
import re
from datetime import date

UNPOST_COMMAND = 0x806E  # 1crcrus.dll menus 135/253: Сделать документ не проведенным
UNPOST_QUESTION = 'Подтвердите отмену проведения документа !'


def unpost_answer(window, cancel=False):
    import scenario77
    if window.get('class') != '#32770' or scenario77.dialog_text(window) != UNPOST_QUESTION:
        raise RuntimeError('unexpected native unpost confirmation')
    button, _, issue = scenario77.answer_plan(dict(target=UNPOST_QUESTION, button='Нет' if cancel else 'Да'), window)
    if issue or button.get('id') != (7 if cancel else 6):
        raise RuntimeError(issue or 'native unpost answer button identity differs')
    return button


def checked_cursor(trip, inspection):
    if (not trip.get('returned') or not trip.get('complete') or trip.get('diagnostics')
            or trip.get('journal_error') or trip.get('journal_match') != '1'
            or not trip.get('journal_current') or trip.get('journal_posted') not in ('0', '1')
            or not trip.get('journal_value') or str(trip.get('journal_hwnd')) not in
            [str(w['hwnd']) for w in inspection.get('chain', [])[:2]]):
        raise RuntimeError('journal target/state was not independently verified')


def unpost_menu(form, inspection):
    return native_menu(form, inspection, UNPOST_COMMAND, 'не проведенным')


def native_menu(form, inspection, command, caption):
    """Read the native menu and update its UI state before dispatching a user command."""
    import ctypes as C
    from ctypes import wintypes as W
    chain = inspection.get('chain', [])
    if len(chain) < 4 or chain[2].get('class') != 'MDIClient':
        raise RuntimeError('unpost requires an inspected MDI journal')
    main = chain[-1]['hwnd']
    if not form.alive(main):
        raise RuntimeError('journal main window is not owned/alive')
    user = form.user
    user.GetMenu.argtypes = [W.HWND]; user.GetMenu.restype = W.HMENU
    user.GetSubMenu.argtypes = [W.HMENU, C.c_int]; user.GetSubMenu.restype = W.HMENU
    user.GetMenuItemCount.argtypes = [W.HMENU]
    user.GetMenuItemID.argtypes = [W.HMENU, C.c_int]; user.GetMenuItemID.restype = W.UINT
    user.GetMenuState.argtypes = [W.HMENU, W.UINT, W.UINT]; user.GetMenuState.restype = W.UINT
    user.GetMenuStringW.argtypes = [W.HMENU, W.UINT, W.LPWSTR, C.c_int, W.UINT]
    found = []
    def visit(menu, depth=0):
        if depth > 5:
            raise RuntimeError('native menu nesting exceeds bound')
        count = user.GetMenuItemCount(menu)
        if not 0 <= count <= 200:
            raise RuntimeError('invalid native menu size')
        for index in range(count):
            sub = user.GetSubMenu(menu, index)
            if sub:
                if not form.send(main, 0x117, sub, index)[0]:  # WM_INITMENUPOPUP: update enabled state
                    raise RuntimeError('native menu state update failed')
                visit(sub, depth + 1)
            elif user.GetMenuItemID(menu, index) == command:
                title = C.create_unicode_buffer(512)
                user.GetMenuStringW(menu, command, title, len(title), 0)
                flags = user.GetMenuState(menu, command, 0)
                found.append(dict(command=command, caption=title.value, flags=flags,
                                  enabled=flags != 0xFFFFFFFF and not flags & 3, main=main))
    visit(user.GetMenu(main))
    if len(found) != 1 or caption not in found[0]['caption'].casefold():
        raise RuntimeError('native journal menu command is missing or ambiguous: ' + str(found))
    return found[0]


def validate_period(parameters, previous, step):
    validate(parameters, parameters.get('form_object'))
    if (parameters.get('fixture_mode') != 'journal_existing' or not parameters.get('fixture_setup')
            or any(s['kind'] != 'journal_period' for s in previous)):
        raise ValueError('journal_period requires journal_existing before find_document')
    try:
        start, end = (date.fromisoformat(step[k]) for k in ('start', 'end'))
        if any(step[k] != d.isoformat() for k, d in (('start', start), ('end', end))) or start > end:
            raise ValueError()
    except (KeyError, ValueError):
        raise ValueError('journal_period requires start <= end, ISO dates YYYY-MM-DD') from None


def read_period(trip):
    if (not trip.get('returned') or not trip.get('complete') or trip.get('diagnostics')
            or trip.get('journal_error')):
        raise RuntimeError('journal period response was not verified')
    try:
        values = tuple(date(*map(int, trip['journal_' + key].split(':'))) for key in ('start', 'end'))
        if values[0] > values[1]:
            raise ValueError()
        return values
    except (KeyError, ValueError, TypeError):
        raise RuntimeError('invalid journal period response') from None


def period_fields(window):
    if window.get('text') != 'Параметры журнала' or window.get('class') != '#32770':
        raise RuntimeError('expected native journal parameters dialog')
    fields = []
    for id_ in (4674, 4676):
        matches = [c for c in window.get('children', []) if c.get('parent') == window['hwnd']
                   and c.get('id') == id_ and c.get('class', '').casefold() == 'bmasked'
                   and c.get('visible') and c.get('enabled')]
        if len(matches) != 1:
            raise RuntimeError('native journal date field is missing or ambiguous')
        fields.append(matches[0])
    return fields


def check_period(step, record):
    before, after = (read_period(record[k]) for k in ('before_period', 'after_period'))
    wanted = before if step.get('cancel') else tuple(date.fromisoformat(step[k]) for k in ('start', 'end'))
    if after != wanted:
        raise RuntimeError(f'journal period mismatch: {after}, expected {wanted}')
    if not record.get('period_closed') or not record.get('answer', {}).get('requested'):
        raise RuntimeError('journal period dialog closing was not verified')


def validate(parameters, name):
    journal = parameters.get('journal_form')
    if not isinstance(journal, str) or not re.fullmatch(
            r'Журнал\.[^\W\d]\w*\.ФормаСписка\.[^\W\d]\w*', journal, re.IGNORECASE):
        raise ValueError('journal mode requires journal_form = Журнал.<Имя>.ФормаСписка.<Форма>')
    if not re.fullmatch(r'Документ\.[^\W\d]\w*', name or '', re.IGNORECASE):
        raise ValueError('journal mode requires a document form_object')
    if parameters.get('fixture_post') or parameters.get('fixture_operations'):
        raise ValueError('journal mode forbids programmatic document posting')
    if not parameters.get('fixture_verify'):
        raise ValueError('journal mode requires fixture_verify')
    return journal


def controller(text, settings, expected):
    """Prepare prerequisites once; keep that result separate from the UI-created reference."""
    helpers = ('Функция Harness77ПодготовитьДанные()\n' + settings['setup'] + '\nКонецФункции\n\n'
               'Функция Harness77ПроверитьДанные(Объект77)\n' + settings['verify'] + '\nКонецФункции\n\n')
    prefix = '''    Если Попытка77Данных = 0 Тогда
        Попытка77Данных = 1;
        Попытка
            Объект77Подготовки = Harness77ПодготовитьДанные();
        Исключение
            Ошибка77Данных = ОписаниеОшибки();
        КонецПопытки;
    КонецЕсли;
    Если Ошибка77Данных <> "" Тогда
        Ответ77 = Ответ77 + "fixture-error:" + Ошибка77Данных + РазделительСтрок;
    ИначеЕсли Команда = "verify" Тогда
        Попытка
            Итог77Данных = Harness77ПроверитьДанные(Объект77Данных);
            Если ТипЗначенияСтр(Итог77Данных) <> "Строка" Тогда
                Ответ77 = Ответ77 + "fixture-verify-error:verification must return a string" + РазделительСтрок;
            Иначе
                Ответ77 = Ответ77 + "fixture-value:" + Итог77Данных + РазделительСтрок;
            КонецЕсли;
        Исключение
            Ответ77 = Ответ77 + "fixture-verify-error:" + ОписаниеОшибки() + РазделительСтрок;
        КонецПопытки;
'''
    branch = '    Если (Команда = "check") ИЛИ (Команда = "open") Тогда'
    if text.count(branch) != 1:
        raise ValueError('unexpected journal controller layout')
    return ('Перем Объект77Данных, Объект77Подготовки, Попытка77Данных, Ошибка77Данных;\n'
            + text.replace('Функция Harness77Ert(', helpers + 'Функция Harness77Ert(', 1).replace(
                branch, prefix + branch.replace('    Если', '    ИначеЕсли', 1))) + (
        '\nПопытка77Данных = 0; Ошибка77Данных = ""; Объект77Данных = 0;\n')


def branches(items, kind):
    result = []
    basis = next((s for s in items if s['kind'] == 'journal_basis'), None)
    children = next((s for s in items if s['kind'] == 'journal_children'), None)
    source_kind = basis['source'] if basis else children['source'] if children else kind
    copying = any(s['kind'] in ('journal_copy', 'journal_basis') and not s.get('cancel') for s in items)
    if any(s['kind'] in ('journal_unpost', 'journal_deletion', 'journal_copy', 'journal_basis', 'journal_children') for s in items):
        result.append(f'''    Если (Номер77Шага <= -105000) И (Номер77Шага > -109000) Тогда
        Попытка
            Ссылка77 = Контекст77Формы.ТекущийДокумент;
            Если Ссылка77 <> Объект77Данных Тогда Возврат "journal-error:journal target changed"; КонецЕсли;
            Док77Чтения = СоздатьОбъект("Документ.{source_kind}");
            Если Док77Чтения.НайтиДокумент(Ссылка77) <> 1 Тогда Возврат "journal-error:target missing"; КонецЕсли;
            Расш77 = СоздатьОбъект("РасширениеФормы");
            Расш77.УстановитьФорму(Контекст77Формы.Форма);
            Ответ77 = "journal-current:" + Harness77Строка(Ссылка77) + РазделительСтрок
                + "journal-match:1" + РазделительСтрок
                + "journal-hwnd:" + Строка(Расш77.Дескриптор) + РазделительСтрок
                + "journal-posted:" + Строка(Док77Чтения.Проведен()) + РазделительСтрок
                + "journal-deleted:" + Строка(Док77Чтения.ПометкаУдаления()) + РазделительСтрок
                + "journal-value:" + Harness77ПроверитьДанные(Объект77Данных);
        Исключение
            Ответ77 = "journal-error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
''')
    if basis and basis.get('return_journal'):
        result.append('''    Если (Номер77Шага <= -109000) И (Номер77Шага > -110000) Тогда
        Попытка
            Сервис77 = СоздатьОбъект("Сервис"); Контекст77Возврата = 0;
            Если Сервис77.АктивныйКонтекст(Контекст77Возврата) <> 1 Тогда Возврат "journal-error:no returned journal context"; КонецЕсли;
            Если Контекст77Возврата.ТекущийДокумент <> Объект77Данных Тогда Возврат "journal-error:returned journal reference differs"; КонецЕсли;
            Расш77 = СоздатьОбъект("РасширениеФормы"); Расш77.УстановитьФорму(Контекст77Возврата.Форма);
            Ответ77 = "journal-return:1" + РазделительСтрок + "journal-reference:" + Harness77Строка(Контекст77Возврата.ТекущийДокумент)
                + РазделительСтрок + "journal-hwnd:" + Строка(Расш77.Дескриптор)
                + РазделительСтрок + "journal-start:" + Harness77ДатаИнтервала(Контекст77Возврата.НачалоИнтервала())
                + РазделительСтрок + "journal-end:" + Harness77ДатаИнтервала(Контекст77Возврата.КонецИнтервала());
        Исключение
            Ответ77 = "journal-error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
''')
    if any(s['kind'] == 'journal_period' for s in items):
        result.append('''    Если (Номер77Шага <= -102000) И (Номер77Шага > -104000) Тогда
        Попытка
            Ответ77 = "journal-start:" + Harness77ДатаИнтервала(Контекст77Формы.НачалоИнтервала()) + РазделительСтрок
                + "journal-end:" + Harness77ДатаИнтервала(Контекст77Формы.КонецИнтервала());
        Исключение
            Ответ77 = "journal-error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
''')
    if children:
        import journal_children77
        result.append(journal_children77.branches(children, kind))
    for step in items:
        number = step["index"]
        if step['kind'] == 'find_document':
            result.append('''    Если (Номер77Шага <= -101000) И (Номер77Шага >= -101200) Тогда
        Попытка
            Ссылка77 = Контекст77Формы.ТекущийДокумент;
            Расш77 = СоздатьОбъект("РасширениеФормы");
            Расш77.УстановитьФорму(Контекст77Формы.Форма);
            Ответ77 = "journal-current:" + Harness77Строка(Ссылка77) + РазделительСтрок
                + "journal-hwnd:" + Строка(Расш77.Дескриптор) + РазделительСтрок
                + "journal-match:" + Строка(?(Ссылка77 = Объект77Данных, 1, 0));
        Исключение
            Ответ77 = "journal-error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
''')
            body = f'''            Сервис77 = СоздатьОбъект("Сервис");
            Новый77Контекст = 0;
            Если Сервис77.АктивныйКонтекст(Новый77Контекст) <> 1 Тогда
                Возврат "journal-error:no active document context";
            КонецЕсли;
            Ссылка77 = Новый77Контекст.ТекущийДокумент();
            Если (ТипЗначенияСтр(Ссылка77) <> "Документ") ИЛИ (ВРег(Ссылка77.Вид()) <> ВРег("{kind}")) Тогда
                Возврат "journal-error:opened document kind mismatch";
            КонецЕсли;
            Если Ссылка77 <> Объект77Данных Тогда Возврат "journal-error:opened another document"; КонецЕсли;
            Док77Чтения = СоздатьОбъект("Документ.{kind}");
            Если (Ссылка77.Выбран() <> 1) ИЛИ (Док77Чтения.НайтиДокумент(Ссылка77) <> 1) Тогда
                Возврат "journal-error:opened document is not saved";
            КонецЕсли;
            Контекст77Формы = Новый77Контекст;
            Расш77 = СоздатьОбъект("РасширениеФормы");
            Расш77.УстановитьФорму(Контекст77Формы.Форма);
            Ответ77 = "journal-opened:1" + РазделительСтрок + "journal-match:1" + РазделительСтрок
                + "journal-reference:" + Harness77Строка(Ссылка77) + РазделительСтрок
                + "journal-hwnd:" + Строка(Расш77.Дескриптор);
'''
        elif step['kind'] == 'journal_basis':
            import journal_basis77
            body = journal_basis77.body(kind, step)
        elif step['kind'] == 'journal_copy':
            import journal_copy77
            body = journal_copy77.body(kind)
        elif step['kind'] == 'create':
            body = f'''            Сервис77 = СоздатьОбъект("Сервис");
            Новый77Контекст = 0;
            Если Сервис77.АктивныйКонтекст(Новый77Контекст) <> 1 Тогда
                Возврат "journal-error:no active document context";
            КонецЕсли;
            Ссылка77 = Новый77Контекст.ТекущийДокумент();
            Если (ТипЗначенияСтр(Ссылка77) <> "Документ") ИЛИ (ВРег(Ссылка77.Вид()) <> ВРег("{kind}")) Тогда
                Возврат "journal-error:active form is not the expected document kind";
            КонецЕсли;
            Если Ссылка77.Выбран() <> 0 Тогда Возврат "journal-error:document was already saved"; КонецЕсли;
            Контекст77Формы = Новый77Контекст;
            Расш77 = СоздатьОбъект("РасширениеФормы");
            Расш77.УстановитьФорму(Контекст77Формы.Форма);
            Ответ77 = "journal-new:1" + РазделительСтрок + "journal-hwnd:" + Строка(Расш77.Дескриптор);
'''
        elif step['kind'] == 'created':
            copy_guard = '''            Если Ссылка77 = Объект77Источник Тогда Возврат "journal-error:copy reused source reference"; КонецЕсли;
''' if copying else ''
            body = f'''            Ссылка77 = Контекст77Формы.ТекущийДокумент();
            Если (ТипЗначенияСтр(Ссылка77) <> "Документ") ИЛИ (ВРег(Ссылка77.Вид()) <> ВРег("{kind}")) Тогда
                Возврат "journal-error:created reference kind mismatch";
            КонецЕсли;
            Док77Чтения = СоздатьОбъект("Документ.{kind}");
            Если (Ссылка77.Выбран() <> 1) ИЛИ (Док77Чтения.НайтиДокумент(Ссылка77) <> 1) Тогда
                Возврат "journal-error:created document is not saved";
            КонецЕсли;
{copy_guard}            Если ТипЗначенияСтр(Объект77Данных) = "Документ" Тогда
                Если {('(Объект77Данных <> Объект77Источник) И (Объект77Данных <> Ссылка77)' if copying else 'Объект77Данных <> Ссылка77')} Тогда Возврат "journal-error:created reference changed"; КонецЕсли;
            КонецЕсли;
            Объект77Данных = Ссылка77;
            Ответ77 = "journal-saved:1" + РазделительСтрок + "journal-reference:" + Harness77Строка(Ссылка77);
'''
            if copying:
                body += '''            Ответ77 = Ответ77 + РазделительСтрок
                + "journal-source:" + Harness77Строка(Объект77Источник) + РазделительСтрок
                + "journal-date:" + Harness77ДатаИнтервала(Док77Чтения.ДатаДок) + РазделительСтрок
                + "journal-number:" + СокрЛП(Док77Чтения.НомерДок) + РазделительСтрок
                + "journal-posted:" + Строка(Док77Чтения.Проведен()) + РазделительСтрок
                + "journal-deleted:" + Строка(Док77Чтения.ПометкаУдаления()) + РазделительСтрок
                + "journal-value:" + Harness77ПроверитьДанные(Объект77Данных);
'''
            if basis:
                body += '            Если Док77Чтения.' + basis['link'] + ' <> Объект77Источник Тогда Возврат "journal-error:saved basis link differs"; КонецЕсли;\n'
                body += '            Ответ77 = Ответ77 + РазделительСтрок + "journal-link:" + Harness77Строка(Док77Чтения.' + basis['link'] + ');\n'
        elif step['kind'] == 'reopen' and basis:
            import scenario77
            number = scenario77.trip_number(step['index'], 1)
            body = f'''            Если Контекст77Формы.{basis['link']} <> Объект77Источник Тогда
                Возврат "journal-error:reopened basis link differs";
            КонецЕсли;
            Ответ77 = "journal-link:" + Harness77Строка(Контекст77Формы.{basis['link']}) + РазделительСтрок
                + "journal-source:" + Harness77Строка(Объект77Источник);
'''
        else:
            continue
        result.append(f'''    Если Номер77Шага = {number} Тогда
        Попытка
{body}        Исключение
            Ответ77 = "journal-error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
''')
    return ''.join(result)


def function(items, kind):
    references = ''
    if any(s['kind'] == 'journal_children' for s in items):
        import journal_children77
        references = journal_children77.reference_function()
    return (references + 'Функция Harness77ДатаИнтервала(Дата77)\n    Возврат Строка(ДатаГод(Дата77)) + ":" + Строка(ДатаМесяц(Дата77)) + ":" + Строка(ДатаЧисло(Дата77));\nКонецФункции\n\nФункция Harness77Журнал(Номер77Шага)\n    Ответ77 = "";\n' + branches(items, kind)
            + '    Возврат Ответ77;\nКонецФункции\n\n')


def select_kind(form, window, caption, evidence=None, cancel=False):  # native; listbox messages marshal strings
    from form_window77 import listbox_items
    import scenario77
    if window.get('text') != 'Выбор вида документа':
        raise RuntimeError('expected the native document-kind chooser')
    lists = [c for c in window.get('children', []) if c.get('parent') == window['hwnd']
             and c.get('class', '').casefold() == 'listbox' and c.get('visible') and c.get('enabled')]
    if len(lists) != 1:
        raise RuntimeError('document-kind chooser needs exactly one listbox')
    hwnd = lists[0]['hwnd']
    names = listbox_items(form, hwnd)
    evidence = evidence if evidence is not None else {}
    evidence['names'] = names
    if cancel:
        button, _, issue = scenario77.answer_plan(dict(target=window['text'], button='Отмена'), window)
        if issue:
            raise RuntimeError(issue)
        evidence.update(cancel=True, answer=form.answer(window, button))
        return evidence
    matches = [i for i, name in enumerate(names) if name.strip().casefold() == caption.strip().casefold()]
    if len(matches) != 1:
        raise RuntimeError(f'document kind {caption!r} is not unique in {names!r}')
    index = matches[0]
    ok, selected, _ = form.send(hwnd, 0x186, index)  # LB_SETCURSEL: standard user selection
    confirmed, current, _ = form.send(hwnd, 0x188)  # LB_GETCURSEL
    if not ok or selected != index or not confirmed or current != index:
        raise RuntimeError('document kind selection did not persist')
    button, field, issue = scenario77.answer_plan(dict(target=window['text'], button='ОК'), window)
    if issue:
        raise RuntimeError(issue)
    answer = form.answer(window, button)
    evidence.update(selected=index, caption=names[index], answer=answer)
    return evidence
