"""041–043: read-only exact selection in single-kind and mixed native child journals."""
import re
import time
import journal77

CHILDREN_COMMAND = 0x806C  # 1crcrus.dll menus 135/253: Подчиненные документы


def validate(parameters, previous, step):
    journal77.validate(parameters, parameters.get('form_object'))
    if (parameters.get('fixture_mode') != 'journal_existing' or not previous
            or previous[-1]['kind'] != 'find_document' or previous[-1].get('open') is not False):
        raise ValueError('journal_children requires immediately preceding find_document open=false')
    for name in ('source', 'link'):
        if not re.fullmatch(r'[^\W\d]\w*', step.get(name, '')):
            raise ValueError('journal_children requires identifier ' + name)
    if not 1 <= step.get('reference', 0) <= 100 or not step.get('expected'):
        raise ValueError('journal_children requires preparation reference slot 1..100 and expected readback')
    journal77.validate(dict(parameters, journal_form=step.get('journal')), parameters['form_object'])
    if step.get('empty') and step.get('cancel'):
        raise ValueError('journal_children empty and cancel are separate cases')
    if 'limit' in step and (type(step['limit']) is not int or not 1 <= step['limit'] <= 100 or step.get('empty')):
        raise ValueError('journal_children limit requires 1..100 and a nonempty search')
    if 'kinds' in step:
        kinds = [k.strip() for k in step['kinds'].split(',')]
        if (not 2 <= len(kinds) <= 10
                or any(not isinstance(k, str) or not re.fullmatch(r'[^\W\d]\w*', k) for k in kinds)
                or len({k.casefold() for k in kinds}) != len(kinds)
                or parameters['form_object'].split('.')[1] not in kinds
                or step['source'].casefold() in {k.casefold() for k in kinds}
                or 'limit' not in step):
            raise ValueError('journal_children kinds requires 2..10 distinct identifiers including the target, excluding source, and limit')
        step['kinds'] = kinds
    if 'browser_visible' in step and 'kinds' not in step:
        raise ValueError('journal_children browser_visible requires explicit mixed kinds')
    if step['source'].casefold() == parameters['form_object'].split('.')[1].casefold():
        raise ValueError('journal_children requires distinct source and child kinds')
    import journal_basis77
    journal_basis77.validate_caption(step)


def branches(step, kind):
    active = '''            Сервис77 = СоздатьОбъект("Сервис"); Новый77Контекст = 0;
            Если Сервис77.АктивныйКонтекст(Новый77Контекст) <> 1 Тогда Возврат "journal-error:no active context"; КонецЕсли;
            Расш77 = СоздатьОбъект("РасширениеФормы"); Расш77.УстановитьФорму(Новый77Контекст.Форма);
'''
    source = active + f'''            Ссылка77 = Новый77Контекст.ТекущийДокумент;
            Если Ссылка77 <> Объект77Данных Тогда Возврат "journal-error:active source changed"; КонецЕсли;
            Док77Чтения = СоздатьОбъект("Документ.{step['source']}");
            Если Док77Чтения.НайтиДокумент(Ссылка77) <> 1 Тогда Возврат "journal-error:source missing"; КонецЕсли;
            Ответ77 = "journal-current:" + Harness77Строка(Ссылка77) + РазделительСтрок
                + "journal-id:" + Harness77Строка(ЗначениеВСтрокуВнутр(Ссылка77)) + РазделительСтрок
                + "journal-match:1" + РазделительСтрок + "journal-hwnd:" + Строка(Расш77.Дескриптор) + РазделительСтрок
                + "journal-posted:" + Строка(Док77Чтения.Проведен()) + РазделительСтрок
                + "journal-deleted:" + Строка(Док77Чтения.ПометкаУдаления()) + РазделительСтрок;
'''
    child = active + f'''            Если Номер77Шага > -112000 Тогда
                Ссылка77 = Новый77Контекст.ТекущийДокумент;
            Иначе
                Ссылка77 = Новый77Контекст.ТекущийДокумент();
            КонецЕсли;
            Ожидаемая77Ссылка = Объект77Подготовки.ПолучитьЗначение({step['reference']});
            Ответ77 = "journal-hwnd:" + Строка(Расш77.Дескриптор) + РазделительСтрок
                + "journal-current:" + Harness77Строка(Ссылка77) + РазделительСтрок
                + "journal-id:" + Harness77Строка(ЗначениеВСтрокуВнутр(Ссылка77)) + РазделительСтрок
                + "journal-source:" + Harness77Строка(Объект77Данных) + РазделительСтрок
                + "journal-source-id:" + Harness77Строка(ЗначениеВСтрокуВнутр(Объект77Данных)) + РазделительСтрок
                + "journal-expected-id:" + Harness77Строка(ЗначениеВСтрокуВнутр(Ожидаемая77Ссылка)) + РазделительСтрок
                + "journal-match:" + Строка(?(Ссылка77 = Ожидаемая77Ссылка, 1, 0)) + РазделительСтрок
                + "journal-empty:" + Строка(ПустоеЗначение(Ссылка77)) + РазделительСтрок;
            Если ПустоеЗначение(Ссылка77) = 0 Тогда
                Если (ТипЗначенияСтр(Ссылка77) <> "Документ") ИЛИ (Ссылка77.Вид() <> "{kind}") Тогда
                    Возврат "journal-error:unexpected subordinate kind";
                КонецЕсли;
                Док77Чтения = СоздатьОбъект("Документ.{kind}");
                Если Док77Чтения.НайтиДокумент(Ссылка77) <> 1 Тогда Возврат "journal-error:child not saved"; КонецЕсли;
                Ответ77 = Ответ77 + "journal-link-id:" + Harness77Строка(ЗначениеВСтрокуВнутр(Док77Чтения.{step['link']})) + РазделительСтрок
                    + "journal-link:" + Строка(?(Док77Чтения.{step['link']} = Объект77Данных, 1, 0)) + РазделительСтрок
                    + "journal-comment:" + Harness77Строка(Док77Чтения.Комментарий) + РазделительСтрок;
                Если Номер77Шага <= -112000 Тогда
                    Если (Ссылка77 <> Ожидаемая77Ссылка) ИЛИ (Новый77Контекст.{step['link']} <> Объект77Данных) Тогда
                        Возврат "journal-error:opened child identity/link differs";
                    КонецЕсли;
                    Ответ77 = Ответ77 + "journal-opened:1" + РазделительСтрок;
                КонецЕсли;
            КонецЕсли;
'''
    if 'kinds' in step:
        allowed = ' ИЛИ '.join(f'(Ссылка77.Вид() = "{name}")' for name in step['kinds'])
        child = child.replace(
            f'(Ссылка77.Вид() <> "{kind}")', f'НЕ ({allowed})').replace(
            f'Док77Чтения = СоздатьОбъект("Документ.{kind}");',
            'Док77Чтения = СоздатьОбъект("Документ." + Ссылка77.Вид());')
        child = child.replace('            Ответ77 = "journal-hwnd:', f'''            Если (ТипЗначенияСтр(Ожидаемая77Ссылка) <> "Документ") Тогда
                Возврат "journal-error:expected subordinate is not a document";
            КонецЕсли;
            Если Ожидаемая77Ссылка.Вид() <> "{kind}" Тогда
                Возврат "journal-error:expected subordinate kind differs";
            КонецЕсли;
            Ответ77 = "journal-hwnd:''')
        child = child.replace('                Док77Чтения = СоздатьОбъект("Документ."', '''                Ответ77 = Ответ77 + "journal-kind:" + Ссылка77.Вид() + РазделительСтрок
                    + "journal-expected-kind:" + Ожидаемая77Ссылка.Вид() + РазделительСтрок;
                Док77Чтения = СоздатьОбъект("Документ."''')
    result = []
    for condition, body in [
        ('((Номер77Шага <= -110000) И (Номер77Шага > -111000)) ИЛИ ((Номер77Шага <= -113000) И (Номер77Шага > -114000))', source),
        ('(Номер77Шага <= -111000) И (Номер77Шага > -113000)', child),
    ]:
        result.append(f'''    Если {condition} Тогда
        Попытка
{body}            Ответ77 = Ответ77 + "journal-value:" + Harness77ПроверитьДанные(Объект77Данных);
        Исключение
            Ответ77 = "journal-error:" + Harness77Строка(ОписаниеОшибки());
        КонецПопытки;
    КонецЕсли;
''')
    return ''.join(result).replace('ЗначениеВСтрокуВнутр(', 'Harness77КодСсылки(')


def validate_metadata(metadata, name, step):
    for child_kind in step.get('kinds', [name.split('.')[1]]):
        if child_kind.casefold() not in metadata.objects()['Документ']:
            raise ValueError('journal_children unknown child kind: ' + child_kind)
        field = metadata.attributes('Документ', child_kind).get(step['link'].casefold())
        if field is None or field.code != 'O' or (field.kind and field.kind.casefold() != step['source'].casefold()):
            raise ValueError('journal_children link must accept the source document kind: ' + child_kind)


def runtime_description(description, step):
    import journal_basis77
    result = journal_basis77.runtime_description(description, step, allow_button='kinds' in step)
    if 'browser_visible' in step:
        if not result.get('browser'):
            raise ValueError('journal_children browser_visible requires a described browser')
        result['browser']['expected_visible'] = step['browser_visible']
    return result


def reference_function():
    # 7.7 serializes a generic journal reference and a typed reference differently,
    # even when reference equality is true. Read both through the same typed object.
    return '''Функция Harness77КодСсылки(Ссылка77)
    Если ПустоеЗначение(Ссылка77) = 1 Тогда Возврат "empty"; КонецЕсли;
    Док77Кода = СоздатьОбъект("Документ." + Ссылка77.Вид());
    Если Док77Кода.НайтиДокумент(Ссылка77) <> 1 Тогда Возврат ""; КонецЕсли;
    Возврат ЗначениеВСтрокуВнутр(Док77Кода.ТекущийДокумент());
КонецФункции

'''


def checked(trip, expected):
    if (not trip.get('returned') or not trip.get('complete') or trip.get('diagnostics')
            or trip.get('journal_error') or trip.get('journal_value') != expected):
        raise RuntimeError('subordinate response/persisted state differs: ' + str(trip))


def checked_child(trip, before, handles, empty=False, opened=False):
    checked(trip, before['journal_value'])
    if (str(trip.get('journal_hwnd')) not in {str(h) for h in handles}
            or trip.get('journal_source_id') != before.get('journal_id')
            or not trip.get('journal_expected_id')):
        raise RuntimeError('subordinate window/source identity differs')
    if empty:
        if trip.get('journal_empty') != '1' or trip.get('journal_match') != '0':
            raise RuntimeError('subordinate journal is not empty')
    elif (trip.get('journal_empty') != '0' or trip.get('journal_match') != '1'
          or trip.get('journal_id') != trip.get('journal_expected_id')
          or trip.get('journal_link_id') != before.get('journal_id') or trip.get('journal_link') != '1'
          or (opened and trip.get('journal_opened') != '1')):
        raise RuntimeError('exact saved child reference/link was not verified')


def checked_candidate(trip, before, handles):
    """042: an unselected row must still belong to this source and owned list."""
    checked(trip, before['journal_value'])
    if (str(trip.get('journal_hwnd')) not in {str(h) for h in handles}
            or trip.get('journal_source_id') != before.get('journal_id')
            or not trip.get('journal_expected_id') or not trip.get('journal_id')
            or trip.get('journal_empty') != '0' or trip.get('journal_link') != '1'
            or trip.get('journal_link_id') != before.get('journal_id')
            or trip.get('journal_match') != str(int(trip['journal_id'] == trip['journal_expected_id']))):
        raise RuntimeError('subordinate search row identity/link/window differs')


def checked_kind(trip, step, target=False):
    """043: admit declared row kinds, but gate opening on the target kind as well."""
    if 'kinds' not in step:
        return
    actual, expected = trip.get('journal_kind'), trip.get('journal_expected_kind')
    if (actual not in step['kinds'] or expected != step['target_kind']
            or (target and actual != expected)):
        raise RuntimeError('subordinate row/target kind differs')


def search_child(form, table, before, handles, step, record, call):
    """Bounded End/Up navigation; never dispatch Enter here."""
    import scenario77
    rows = record['child_search'] = []
    seen = set()
    for index in range(step['limit']):
        action = form.post_key(table['hwnd'], *scenario77.KEYS['end' if index == 0 else 'up'])
        row = dict(action=action)
        rows.append(row)
        if not action.get('returned'):
            raise RuntimeError('subordinate search key failed')
        trip = row['round_trip'] = call(-111001-index)
        checked_candidate(trip, before, handles)
        checked_kind(trip, step)
        if index and trip['journal_expected_id'] != rows[0]['round_trip']['journal_expected_id']:
            raise RuntimeError('subordinate expected reference changed during search')
        if trip['journal_match'] == '1':
            checked_child(trip, before, handles)
            checked_kind(trip, step, target=True)
            record['selected_child'] = trip
            # A fresh response after the last movement gates Enter (or cancellation).
            recheck = record['selection_recheck'] = call(-111900)
            checked_child(recheck, before, handles)
            checked_kind(recheck, step, target=True)
            if {k: v for k, v in recheck.items() if k.startswith('journal_')} != {k: v for k, v in trip.items() if k.startswith('journal_')}:
                raise RuntimeError('subordinate selection changed before Enter')
            return trip
        if trip['journal_id'] in seen:
            raise RuntimeError('subordinate reference not found at list boundary')
        seen.add(trip['journal_id'])
    raise RuntimeError('subordinate search limit exhausted before exact reference')


def inspect_frame(form, description, frame):
    from form_window77 import expected_geometry, edged_ids, fit_units, judge_layout, judge_captions, inside
    expected = expected_geometry(description)
    opened = form.inspect(list(expected), frame=frame)
    if not opened.get('found') or len(opened.get('chain', [])) < 2 or opened['chain'][1].get('hwnd') != frame:
        raise RuntimeError('owned subordinate frame/layout missing')
    opened['units'] = fit_units(expected, {c['id']: tuple(c['rect']) for c in opened['controls']}, edged=edged_ids(description))
    issues = judge_layout(description, opened) + judge_captions(description, opened)
    if description.get('browser'):
        tables = [c for c in opened['controls'] if c.get('id') == 4151]
        if (len(tables) != 1 or tables[0].get('class', '').casefold() != 'browse'
                or tables[0].get('visible') is not description['browser'].get('expected_visible', True) or not tables[0].get('enabled')
                or not inside(tuple(tables[0]['rect']), opened['chain'][0]['client_size'])
                or any(v <= 0 for v in tables[0]['rect'][2:])):
            issues.append('journal browse rectangle/class/state is invalid: ' + str(tables))
    if issues:
        raise RuntimeError('subordinate frame layout/captions differ: ' + str(issues))
    return opened


def close_frame(watcher, form, frame):
    import scenario77
    from form_window77 import Pending
    record = dict(hwnd=frame, message='WM_CLOSE', requested=True, identity_rechecked=True)
    seen = form.top_windows()
    pending = Pending(form, frame, 0x10, 0, 0)
    until = time.monotonic() + 10
    while time.monotonic() < until:
        window = form.modal_window(seen)
        if window:
            record['question'] = window
            if record.get('answer') or not scenario77.dialog_text(window).startswith('Сохранить Документ?'):
                raise RuntimeError('unexpected modal window on read-only close')
            button, _, issue = scenario77.answer_plan(dict(target='Сохранить Документ?', button='Нет'), window)
            if issue:
                raise RuntimeError(issue)
            record['answer'] = form.answer(window, button)
            if not record['answer'].get('requested'):
                raise RuntimeError('read-only close refusal was not sent')
            seen.add(window['hwnd'])
        if pending.done() and not form.alive(frame):
            record.update(pending.outcome or {})
            record['destroyed'] = True
            return record
        if watcher.stopped.wait(.05):
            break
    raise RuntimeError('read-only subordinate frame did not close')


def execute(watcher, form, inspection, step, record):
    import scenario77
    from form_window77 import Pending
    def call(number):
        trip = watcher.round_trip(number)
        record['calls'].append(dict(trip, number=number))
        return trip
    record['calls'] = []
    before = record['before_children'] = call(-110001)
    journal77.checked_cursor(before, inspection)
    checked(before, step['expected'])
    if not before.get('journal_id'):
        raise RuntimeError('serialized source identity missing')
    record['menu'] = journal77.native_menu(form, inspection, CHILDREN_COMMAND, 'чиненные документы')
    if not record['menu']['enabled']:
        raise RuntimeError('native subordinate-documents command disabled')
    old = record['before_windows'] = form.inventory()
    old_handles = {w['hwnd'] for w in old}
    mdi = inspection['chain'][2]['hwnd']
    record['action'] = dict(requested=True, command=CHILDREN_COMMAND, hwnd=inspection['chain'][1]['hwnd'],
                            message='WM_COMMAND', identity_rechecked=True)
    pending = Pending(form, record['action']['hwnd'], 0x111, CHILDREN_COMMAND, 0)
    until = time.monotonic() + 10
    while not pending.done() and time.monotonic() < until:
        if watcher.stopped.wait(.05):
            break
    record['action'].update(pending.outcome or {})
    if not pending.done() or not record['action'].get('returned'):
        raise RuntimeError('subordinate command did not return')
    inventory = record['children_windows'] = form.inventory()
    frames = [w for w in inventory if w.get('parent') == mdi and w['hwnd'] not in old_handles
              and w.get('visible') and w.get('enabled')]
    caption = watcher.children_description['form']['caption'] + ' ' + before['journal_current']
    if len(frames) != 1 or frames[0].get('text') != caption:
        raise RuntimeError('new subordinate journal frame/caption differs: ' + str(frames))
    frame, document_frame = frames[0]['hwnd'], None
    try:
        children = record['children_form'] = inspect_frame(form, watcher.children_description, frame)
        table = next(c for c in children['controls'] if c['id'] == scenario77.TABLE_WINDOW_ID)
        record['focus'] = form.give_focus(children['chain'][0]['hwnd'], table['hwnd'])
        handles = [w['hwnd'] for w in children['chain'][:2]]
        if 'limit' in step:
            selected = search_child(form, table, before, handles, step, record, call)
        else:
            record['selection_key'] = form.post_key(table['hwnd'], *scenario77.KEYS['end'])
            if not record['selection_key'].get('returned'):
                raise RuntimeError('subordinate selection key failed')
            selected = record['selected_child'] = call(-111001)
            checked_child(selected, before, handles, empty=step.get('empty', False))
            record['boundary_key'] = form.post_key(table['hwnd'], *scenario77.KEYS['up'])
            if not record['boundary_key'].get('returned'):
                raise RuntimeError('subordinate boundary key failed')
            boundary = record['boundary_child'] = call(-111003)
            checked_child(boundary, before, handles, empty=step.get('empty', False))
            if boundary.get('journal_id') != selected.get('journal_id'):
                raise RuntimeError('subordinate journal contains more than the declared single child')
        record['exact_selection_verified'] = True
        if not (step.get('empty') or step.get('cancel')):
            record['open_action'] = form.post_key(table['hwnd'], *scenario77.KEYS['enter'])
            if not record['open_action'].get('returned'):
                raise RuntimeError('subordinate Enter failed')
            opened = record['opened_child'] = call(-112001)
            checked(opened, before['journal_value'])
            new_inventory = record['opened_windows'] = form.inventory()
            new_frames = [w for w in new_inventory if w.get('parent') == mdi
                          and w['hwnd'] not in {w['hwnd'] for w in inventory} and w.get('visible') and w.get('enabled')]
            if len(new_frames) != 1:
                raise RuntimeError('new saved child document frame missing/ambiguous')
            document_frame = new_frames[0]['hwnd']
            description = runtime_description(watcher.created_description, step)
            document = record['opened_form'] = inspect_frame(form, description, document_frame)
            checked_child(opened, before, [w['hwnd'] for w in document['chain'][:2]], opened=True)
            checked_kind(opened, step, target=True)
            if opened['journal_id'] != selected['journal_id']:
                raise RuntimeError('Enter opened another child')
            record['document_close'] = close_frame(watcher, form, document_frame)
            document_frame = None
            record['returned_child'] = call(-111901 if 'limit' in step else -111002)
            checked_child(record['returned_child'], before, [w['hwnd'] for w in children['chain'][:2]])
            checked_kind(record['returned_child'], step, target=True)
        record['children_close'] = close_frame(watcher, form, frame)
        frame = None
    finally:
        if document_frame and form.alive(document_frame):
            record['document_cleanup'] = close_frame(watcher, form, document_frame)
        if frame and form.alive(frame):
            record['children_cleanup'] = close_frame(watcher, form, frame)
    after = record['after_children'] = call(-113001)
    journal77.checked_cursor(after, inspection)
    checked(after, before['journal_value'])
    if any(after.get(k) != before.get(k) for k in ('journal_current', 'journal_id', 'journal_posted', 'journal_deleted', 'journal_hwnd')):
        raise RuntimeError('return did not preserve original journal/source')
    record['after_windows'] = form.inventory()
    if any(w.get('parent') == mdi and w['hwnd'] not in old_handles for w in record['after_windows']):
        raise RuntimeError('subordinate navigation left an extra MDI frame')
    record['round_trip'] = after
    record['return_verified'] = True
