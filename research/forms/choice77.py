"""Task 028: catalog choice in a document column; no assignment to the form's reference.

The controller finds a unique element by its full name, positions the *choice list* with
АктивизироватьОбъект, and checks the reference returned by Enter (or unchanged by Escape).
The watcher verifies the list's HWND against РасширениеФормы before sending either key.
"""

def request(index, stage):
    """Dedicated negative request numbers; ordinary step calls are positive."""
    return -(index * 10 + stage)


def new_frames(windows, seen):
    """New visible MDI children; protocol viewers under the message pane are not forms."""
    by_handle = {w['hwnd']: w for w in windows}
    return [w for w in windows if w['hwnd'] not in seen and w.get('visible')
            and by_handle.get(w.get('parent'), {}).get('class') == 'MDIClient']


def choice_window(windows, seen):
    """One new visible MDI choice frame and its single dialog/browse; refuse ambiguous layouts."""
    frames = new_frames(windows, seen)
    if not frames:
        return None, 'no choice form opened'
    if len(frames) != 1:
        return None, f'{len(frames)} new MDI forms opened'
    frame = frames[0]
    if '(Выбор)' not in frame.get('text', ''):
        return None, f"an unexpected form {frame.get('text')!r} opened"
    dialogs = [w for w in windows if w.get('parent') == frame['hwnd'] and w.get('class') == '#32770'
               and w.get('visible') and w.get('enabled')]
    lists = [w for w in windows if any(w.get('parent') == d['hwnd'] for d in dialogs)
             and w.get('class') == 'browse' and w.get('id') == 4151 and w.get('visible') and w.get('enabled')]
    if len(lists) != 1:
        return None, f'the choice form has {len(lists)} enabled lists'
    dialog = next(d for d in dialogs if lists[0]['parent'] == d['hwnd'])
    return {'frame': frame, 'dialog': dialog, 'list': lists[0]}, None


def catalog_popup(windows, seen, focus):
    """The floating list of catalog kinds opened by a compound reference."""
    lists = [w for w in windows if w['hwnd'] == (focus or {}).get('hwnd') and w['hwnd'] not in seen
             and w.get('class', '').casefold() == 'listbox' and w.get('visible') and w.get('enabled')]
    if len(lists) != 1:
        return None
    item = lists[0]
    frame = next((w for w in windows if w['hwnd'] == item.get('parent') and w['hwnd'] not in seen
                  and not w.get('parent') and w.get('class', '').startswith('Afx:')
                  and w.get('visible') and w.get('enabled')), None)
    return {'frame': frame, 'list': item} if frame else None


def select_catalog(form, popup, caption, evidence):
    """Select an exact popup entry and post Enter to its still-focused list."""
    from form_window77 import listbox_items
    from scenario77 import KEYS
    hwnd = popup['list']['hwnd']
    names = evidence['names'] = listbox_items(form, hwnd)
    matches = [i for i, name in enumerate(names) if name.strip().casefold() == caption.strip().casefold()]
    if len(matches) != 1:
        raise RuntimeError(f'catalog caption {caption!r} is not unique in {names!r}')
    index = matches[0]
    ok, selected, _ = form.send(hwnd, 0x186, index)  # LB_SETCURSEL
    confirmed, current, _ = form.send(hwnd, 0x188)  # LB_GETCURSEL
    if not ok or selected != index or not confirmed or current != index or (form.focused() or {}).get('hwnd') != hwnd:
        raise RuntimeError('catalog selection or focus changed before Enter')
    evidence.update(index=index, caption=names[index], key=form.post_key(hwnd, *KEYS['enter']))
    if not evidence['key'].get('returned'):
        raise RuntimeError('catalog selection key did not return')


GLOBALS = 'Перем Контекст77Выбора, Объект77Выбора, До77Выбора;\n'


def branches(items):
    """1C code for preparing, positioning, checking the cursor, and checking the returned reference."""
    from scenario77 import _literal
    result = []
    for step in items:
        if step['kind'] != 'choose':
            continue
        index, column, catalog = step['index'], step['column'], step['catalog']
        cancel = step.get('cancel', False)
        table_answer = ' + Harness77Таблица()' if 'catalog_caption' in step else ''
        before_popup = '            Возврат Harness77Таблица();\n' if table_answer else ''
        find = '' if cancel else f'''
            Спр77Выбора = СоздатьОбъект({_literal('Справочник.' + catalog)});
            Найдено77Выбора = 0;
            Спр77Выбора.ВыбратьЭлементы();
            Пока Спр77Выбора.ПолучитьЭлемент() = 1 Цикл
                Если (Спр77Выбора.ЭтоГруппа() = 0) И (ВРег(СокрЛП(Спр77Выбора.Наименование)) = ВРег({_literal(step['text'].strip())})) Тогда
                    Найдено77Выбора = Найдено77Выбора + 1;
                    Объект77Выбора = Спр77Выбора.ТекущийЭлемент();
                КонецЕсли;
            КонецЦикла;
            Если Найдено77Выбора <> 1 Тогда
                Возврат "error:choice needs one catalog element, found " + Строка(Найдено77Выбора);
            КонецЕсли;
            Контекст77Выбора.АктивизироватьОбъект(Объект77Выбора);
'''
        result.append(f'''    Если Номер77Шага = {index} Тогда
        Попытка
            Контекст77Выбора = 0;
            Объект77Выбора = 0;
            Если Контекст77Формы.КоличествоСтрок() = 0 Тогда Возврат "error:the table has no row"; КонецЕсли;
            До77Выбора = Контекст77Формы.{column};
            Контекст77Формы.Активизировать({_literal(column)}, 1);
        Исключение
            Возврат "error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
    Если Номер77Шага = {request(index, 1)} Тогда
        Попытка
            Сервис77Выбора = СоздатьОбъект("Сервис");
            Если Сервис77Выбора.АктивныйКонтекст(Контекст77Выбора) <> 1 Тогда Возврат "error:no active choice context"; КонецЕсли;
            Текущий77Выбора = Контекст77Выбора.ТекущийЭлемент();
            Если (ТипЗначенияСтр(Текущий77Выбора) <> "Справочник") ИЛИ (ВРег(Текущий77Выбора.Вид()) <> ВРег({_literal(catalog)})) Тогда
                Возврат "error:the active form is not the expected catalog";
            КонецЕсли;
            Расш77Выбора = СоздатьОбъект("РасширениеФормы");
            Расш77Выбора.УстановитьФорму(Контекст77Выбора.Форма);
            ОтветВыбора77 = "choice-hwnd:" + Строка(Расш77Выбора.Дескриптор);
            Возврат ОтветВыбора77;
        Исключение
            Возврат "error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
    Если Номер77Шага = {request(index, 2)} Тогда
        Попытка
{find}            Возврат "choice-positioned:1";
        Исключение
            Возврат "error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
    Если Номер77Шага = {request(index, 3)} Тогда
        Попытка
            Текущий77Выбора = Контекст77Выбора.ТекущийЭлемент();
            ОтветВыбора77 = "choice-current:" + Harness77Строка(Текущий77Выбора);
            Если {'1 = 1' if cancel else 'Текущий77Выбора = Объект77Выбора'} Тогда
                ОтветВыбора77 = ОтветВыбора77 + РазделительСтрок + "choice-ready:1";
            Иначе
                ОтветВыбора77 = ОтветВыбора77 + РазделительСтрок + "choice-ready:0";
            КонецЕсли;
            Возврат ОтветВыбора77;
        Исключение
            Возврат "error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
    Если Номер77Шага = {request(index, 4)} Тогда
        Попытка
            Если Контекст77Формы.{column} = {'До77Выбора' if cancel else 'Объект77Выбора'} Тогда
                ОтветВыбора77 = "choice-result:1";
            Иначе
                ОтветВыбора77 = "choice-result:0";
            КонецЕсли;
            ОтветВыбора77 = ОтветВыбора77 + РазделительСтрок + "choice-value:" + Harness77Строка(Контекст77Формы.{column});
            Контекст77Выбора = 0;
            Возврат ОтветВыбора77{table_answer};
        Исключение
            Возврат "error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
    Если Номер77Шага = {request(index, 5)} Тогда
        Попытка
            Контекст77Выбора = 0;
            Объект77Выбора = 0;
            Если Контекст77Формы.КоличествоСтрок() = 0 Тогда Возврат "error:the table has no row"; КонецЕсли;
            До77Выбора = Контекст77Формы.{column};
{before_popup}        Исключение
            Возврат "error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
''')
    return ''.join(result)


def function(items):
    return '''Функция Harness77Выбор(Номер77Шага)
''' + branches(items) + '''    Возврат "";
КонецФункции

'''
