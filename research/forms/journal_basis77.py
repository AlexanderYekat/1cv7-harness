"""040: native input-on-basis, with separate source and result identities."""
import re
import time

import journal77

BASIS_COMMAND = 0x806D  # 1crcrus.dll menus 135/253: Ввести на основании (Alt+F9)


def validate(parameters, previous, step):
    journal77.validate(parameters, parameters.get('form_object'))
    if (parameters.get('fixture_mode') != 'journal_existing' or not previous
            or previous[-1]['kind'] != 'find_document' or previous[-1].get('open') is not False):
        raise ValueError('journal_basis requires an immediately preceding find_document open=false')
    for name in ('source', 'link'):
        if not re.fullmatch(r'[^\W\d]\w*', step.get(name, '')):
            raise ValueError('journal_basis requires an identifier for ' + name)
    if step['source'].casefold() == parameters['form_object'].split('.')[1].casefold():
        raise ValueError('journal_basis requires distinct source and result document kinds')
    validate_caption(step)
    if 'return_journal' in step:
        journal77.validate(dict(parameters, journal_form=step['return_journal']), parameters['form_object'])


def validate_caption(step):
    if ('caption_control' in step) != ('caption_text' in step):
        raise ValueError('runtime caption requires caption_control and caption_text')
    if 'caption_control' in step and not re.fullmatch(r'[^\W\d]\w*', step['caption_control']):
        raise ValueError('runtime caption requires a control identifier')


def runtime_description(description, step, allow_button=False):
    """Explicit scenario expectation for a caption changed by the original form module."""
    import copy
    result = copy.deepcopy(description)
    if 'caption_control' in step:
        identifier = step['caption_control']
        controls = [c for c in result['controls'] if c.get('identifier', '').casefold() == identifier.casefold()]
        if len(controls) != 1 or not ((controls[0]['class'] == 'STATIC' and not controls[0].get('formula'))
                                    or (allow_button and controls[0]['class'] == 'BUTTON')):
            raise ValueError('runtime caption must name one static label without a formula or an explicitly allowed button: ' + identifier)
        controls[0]['caption'] = step['caption_text']
    return result


def checked_new(trip):
    if (not trip.get('returned') or not trip.get('complete') or trip.get('diagnostics')
            or trip.get('journal_error') or trip.get('journal_new') != '1'
            or trip.get('journal_basis') != '1' or not trip.get('journal_source')
            or trip.get('journal_link') != trip.get('journal_source')
            or not trip.get('journal_hwnd') or not trip.get('journal_value')
            or not trip.get('journal_date') or not trip.get('journal_number')
            or not trip.get('journal_comment') or trip.get('journal_posted') != '0'
            or trip.get('journal_deleted') != '0'):
        raise RuntimeError('new unsaved based document/source/link/state was not verified')


def body(kind, step):
    import journal_copy77
    if step.get('cancel'):
        return ''
    # The shared read-only active-context checks do not create or save a document.
    text = journal_copy77.body(kind).replace('journal-copy:1', 'journal-basis:1')
    anchor = '            Объект77Источник = Объект77Данных;'
    return text.replace(anchor, f'''            Если Новый77Контекст.{step['link']} <> Объект77Данных Тогда
                Возврат "journal-error:basis reference mismatch";
            КонецЕсли;
            Если Новый77Контекст.Комментарий <> ("Введен на основании: " + глПредставлениеДокумента(Объект77Данных)) Тогда
                Возврат "journal-error:basis comment mismatch";
            КонецЕсли;
{anchor}''').replace('                + "journal-source:"', f'''                + "journal-link:" + Harness77Строка(Контекст77Формы.{step['link']}) + РазделительСтрок
                + "journal-comment:" + Harness77Строка(Контекст77Формы.Комментарий) + РазделительСтрок
                + "journal-source:"''')


def execute(watcher, form, inspection, step, record):
    from form_window77 import Pending, expected_geometry, edged_ids, fit_units, judge_layout, judge_captions
    import scenario77
    before = record['before_basis'] = watcher.round_trip(-108000 - step['index'])
    record['calls'] = [dict(before, number=-108000 - step['index'])]
    journal77.checked_cursor(before, inspection)
    if before.get('journal_deleted') not in ('0', '1'):
        raise RuntimeError('saved basis deletion state missing')
    menu = record['menu'] = journal77.native_menu(form, inspection, BASIS_COMMAND, 'ввести на основании')
    if not menu['enabled']:
        raise RuntimeError('native input-on-basis command disabled')
    record['before_windows'] = form.inventory()
    old = {w['hwnd'] for w in record['before_windows']}
    seen = form.top_windows()
    action = record['action'] = dict(requested=True, command=BASIS_COMMAND,
                                    hwnd=inspection['chain'][1]['hwnd'], posted=False,
                                    message='WM_COMMAND', identity_rechecked=True)
    pending = Pending(form, action['hwnd'], 0x111, BASIS_COMMAND, 0)
    chooser = None
    started = time.monotonic()
    while time.monotonic() - started < 15:
        chooser = form.modal_window(seen)
        if chooser:
            break
        if watcher.stopped.wait(0.05):
            break
    record['kind_window'] = chooser
    if chooser is None:
        raise RuntimeError('no native input-on-basis kind chooser opened')
    try:
        record['kind_selection'] = {}
        record['kind_selection'] = journal77.select_kind(form, chooser, step['target'],
            evidence=record['kind_selection'], cancel=step.get('cancel', False))
        if not record['kind_selection']['answer'].get('requested'):
            raise RuntimeError('input-on-basis chooser answer was not requested')
    except Exception:
        button = scenario77.safe_button(chooser)
        record['unexpected_cleanup'] = form.answer(chooser, button) if button else {'refused': 'no safe answer'}
        raise
    started = time.monotonic()
    while time.monotonic() - started < 15:
        if not form.alive(chooser['hwnd']) and pending.done():
            break
        window = form.modal_window(seen | {chooser['hwnd']})
        if window:
            record['unexpected_window'] = window
            button = scenario77.safe_button(window)
            record['unexpected_cleanup'] = form.answer(window, button) if button else {'refused': 'no safe answer'}
            raise RuntimeError('unexpected modal window during input-on-basis')
        if watcher.stopped.wait(0.05):
            break
    action.update(pending.outcome or {})
    if form.alive(chooser['hwnd']) or not pending.done() or not action.get('returned'):
        raise RuntimeError('native input-on-basis command/chooser did not return')
    action['posted'] = True
    if step.get('cancel'):
        after = record['after_cancel'] = watcher.round_trip(-108000 - step['index'] - 100)
        record['calls'].append(dict(after, number=-108000 - step['index'] - 100))
        journal77.checked_cursor(after, inspection)
        if any(before[k] != after[k] for k in ('journal_current', 'journal_value', 'journal_posted', 'journal_deleted')):
            raise RuntimeError('cancelled chooser altered source/neighbors/count')
        record['chooser_closed'] = True
        record['after_windows'] = form.inventory()
        return inspection
    trip = record['round_trip'] = watcher.round_trip(step['index'])
    record['calls'].append(dict(trip, number=step['index']))
    checked_new(trip)
    if trip['journal_source'] != before['journal_current'] or trip['journal_value'] != before['journal_value']:
        raise RuntimeError('input-on-basis changed persisted source/neighbors/count')
    description = watcher.created_description
    expected = expected_geometry(description)
    created = record['created_form'] = form.inspect(list(expected))
    if not created.get('found'):
        raise RuntimeError('based document form not found')
    created['units'] = fit_units(expected, {c['id']: tuple(c['rect']) for c in created['controls']},
                                edged=edged_ids(description))
    issues = judge_layout(description, created) + judge_captions(description, created)
    hwnd = int(trip.get('journal_hwnd', '0'))
    if issues or hwnd not in [w['hwnd'] for w in created['chain'][:2]] or hwnd in old:
        raise RuntimeError('based document form identity/layout mismatch: ' + str(issues))
    record['after_windows'] = form.inventory()
    record['new_form_verified'] = True
    return created


def returned_journal(watcher, form, step, frames, chain):
    """Allow exactly the declared journal after a saved based document's closing click."""
    from form_window77 import expected_geometry, edged_ids, fit_units, judge_layout, judge_captions
    description = getattr(watcher, 'return_description', None)
    if not description or step.get('kind') != 'click' or not step.get('closes') or len(frames) != 1:
        return False
    prior = watcher.steps[:step['index'] - 1]
    if (not any(s['kind'] == 'created' for s in prior)
            or not any(s['kind'] == 'journal_basis' and s.get('return_journal') and not s.get('cancel') for s in prior)):
        return False
    number = -109000 - step['index']
    trip = dict(watcher.round_trip(number), number=number)
    chain.trips.append(trip)
    if (not trip.get('returned') or not trip.get('complete') or trip.get('diagnostics')
            or trip.get('journal_error') or trip.get('journal_return') != '1'
            or not trip.get('journal_reference')):
        raise RuntimeError('returned journal/current saved reference not verified')
    expected = expected_geometry(description)
    opened = form.inspect(list(expected))
    if not opened.get('found'):
        raise RuntimeError('declared returned journal form not found')
    opened['units'] = fit_units(expected, {c['id']: tuple(c['rect']) for c in opened['controls']}, edged=edged_ids(description))
    issues = judge_layout(description, opened) + judge_captions(description, opened)
    hwnd = int(trip.get('journal_hwnd', '0'))
    if (issues or hwnd != frames[0]['hwnd'] or hwnd not in [w['hwnd'] for w in opened['chain'][:2]]
            or not frames[0].get('text', '').startswith(description['form']['caption'] + ' (')):
        raise RuntimeError('returned journal identity/layout/caption differs: ' + str(issues))
    chain.record['returned_journal'] = dict(inspection=opened, frame=frames[0], round_trip=trip)
    return True
