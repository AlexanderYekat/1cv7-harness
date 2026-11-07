"""Tasks 034–035: create or find/open through a journal's native keyboard commands.

034 captures a newly saved reference; 035 compares every cursor reference with
the prepared saved target before Enter. Both bind a fresh owned document HWND.
"""
import re
from datetime import date


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
    for step in items:
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
            body = f'''            Ссылка77 = Контекст77Формы.ТекущийДокумент();
            Если (ТипЗначенияСтр(Ссылка77) <> "Документ") ИЛИ (ВРег(Ссылка77.Вид()) <> ВРег("{kind}")) Тогда
                Возврат "journal-error:created reference kind mismatch";
            КонецЕсли;
            Док77Чтения = СоздатьОбъект("Документ.{kind}");
            Если (Ссылка77.Выбран() <> 1) ИЛИ (Док77Чтения.НайтиДокумент(Ссылка77) <> 1) Тогда
                Возврат "journal-error:created document is not saved";
            КонецЕсли;
            Если ТипЗначенияСтр(Объект77Данных) = "Документ" Тогда
                Если Объект77Данных <> Ссылка77 Тогда Возврат "journal-error:created reference changed"; КонецЕсли;
            КонецЕсли;
            Объект77Данных = Ссылка77;
            Ответ77 = "journal-saved:1" + РазделительСтрок + "journal-reference:" + Harness77Строка(Ссылка77);
'''
        else:
            continue
        result.append(f'''    Если Номер77Шага = {step['index']} Тогда
        Попытка
{body}        Исключение
            Ответ77 = "journal-error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
''')
    return ''.join(result)


def function(items, kind):
    return ('Функция Harness77ДатаИнтервала(Дата77)\n    Возврат Строка(ДатаГод(Дата77)) + ":" + Строка(ДатаМесяц(Дата77)) + ":" + Строка(ДатаЧисло(Дата77));\nКонецФункции\n\nФункция Harness77Журнал(Номер77Шага)\n    Ответ77 = "";\n' + branches(items, kind)
            + '    Возврат Ответ77;\nКонецФункции\n\n')


def select_kind(form, window, caption):  # native; system listbox messages marshal strings
    import ctypes as C
    import scenario77
    if window.get('text') != 'Выбор вида документа':
        raise RuntimeError('expected the native document-kind chooser')
    lists = [c for c in window.get('children', []) if c.get('parent') == window['hwnd']
             and c.get('class', '').casefold() == 'listbox' and c.get('visible') and c.get('enabled')]
    if len(lists) != 1:
        raise RuntimeError('document-kind chooser needs exactly one listbox')
    hwnd = lists[0]['hwnd']
    ok, count, _ = form.send(hwnd, 0x18B)  # LB_GETCOUNT
    if not ok or not 0 < count < 1000:
        raise RuntimeError('invalid document-kind list size')
    names = []
    for index in range(count):
        ok, length, _ = form.send(hwnd, 0x18A, index)  # LB_GETTEXTLEN
        if not ok or not 0 <= length < 4096:
            raise RuntimeError('invalid document-kind text length')
        buffer = C.create_unicode_buffer(length + 1)
        ok, read, _ = form.send(hwnd, 0x189, index, C.addressof(buffer))  # LB_GETTEXT
        if not ok or read != length:
            raise RuntimeError('document-kind text could not be read')
        names.append(buffer.value)
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
    return dict(names=names, selected=index, caption=names[index], answer=answer)
