"""Task 028: refuse ambiguous choices and require the returned reference, separately from UI success."""
import copy
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import choice77
import scenario77
from test_scenario77 import TABLE, DESCRIPTION, trip
import form_launcher77 as form


def resolved(*items, table=None):
    table = copy.deepcopy(TABLE if table is None else table)
    for field in table['fields']:
        if field['identifier'] == 'Товар':
            field['kind'] = 'Номенклатура'
    return scenario77.resolve(scenario77.steps({'steps': list(items)}), dict(DESCRIPTION, browser=table))


def windows():
    return [
        {'hwnd': 1, 'class': 'MDIClient'},
        {'hwnd': 2, 'class': 'frame', 'parent': 1, 'text': 'Документ', 'visible': True},
        {'hwnd': 3, 'class': 'frame', 'parent': 1, 'text': 'Справочник: Номенклатура (Выбор)', 'visible': True},
        {'hwnd': 4, 'class': '#32770', 'parent': 3, 'visible': True, 'enabled': True},
        {'hwnd': 5, 'class': 'browse', 'parent': 4, 'id': 4151, 'visible': True, 'enabled': True},
    ]


class ChoiceTests(unittest.TestCase):
    def test_choose_by_column_and_cancel(self):
        items = resolved({'choose': 'товар', 'text': 'Товар 028'}, {'choose': 'Товар', 'cancel': True})
        self.assertEqual([(s['column'], s['catalog'], s['column_window']) for s in items],
                         [('Товар', 'Номенклатура', 4159)] * 2)
        self.assertIn('choose', scenario77.ACTIONS)

    def test_invalid_and_contradictory_choices(self):
        for item in ({'choose': 'Товар'}, {'choose': 'Товар', 'text': ''}, {'choose': 'Товар', 'text': ' '},
                     {'choose': 'Товар', 'cancel': False}, {'choose': 'Товар', 'cancel': 1},
                     {'choose': 'Товар', 'text': 'x', 'cancel': True}, {'choose': 'Товар', 'text': 'x', 'row': 2},
                     {'choose': 'Товар', 'text': 'x\ny'}):
            with self.subTest(item=item), self.assertRaises(ValueError):
                scenario77.steps({'steps': [item]})

    def test_choose_needs_a_named_catalog_column(self):
        for target in ('Количество', 'НетТакой', 'N'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                resolved({'choose': target, 'text': 'x'})
        with self.assertRaisesRegex(ValueError, 'named catalog'):
            scenario77.resolve(scenario77.steps({'steps': [{'choose': 'Товар', 'text': 'x'}]}),
                               dict(DESCRIPTION, browser=TABLE))
        with self.assertRaisesRegex(ValueError, 'a list takes key'):
            resolved({'choose': 'Товар', 'text': 'x'}, table=dict(TABLE, document=False))
        with self.assertRaisesRegex(ValueError, 'has no table part'):
            scenario77.resolve(scenario77.steps({'steps': [{'choose': 'Товар', 'text': 'x'}]}), DESCRIPTION)

    def test_formula_dialogs_follow_choice(self):
        items = resolved({'choose': 'Товар', 'text': 'x'}, {'dialog': 'Предупреждение', 'button': 'ОК'})
        self.assertEqual((items[0]['dialogs'], items[1]['chain'], items[1]['last']), (1, 1, True))

    def test_find_and_compare_references_without_assigning_the_field(self):
        items = resolved({'choose': 'Товар', 'text': 'Имя "028"'}, {'choose': 'Товар', 'cancel': True})
        text = scenario77.controller(form.CONTROLLER, items, table=True)
        self.assertTrue(text.startswith(choice77.GLOBALS))
        self.assertIn('Контекст77Выбора.АктивизироватьОбъект(Объект77Выбора);', text)
        self.assertIn('Если Найдено77Выбора <> 1 Тогда', text)
        self.assertIn('ВРег("Имя ""028""")', text)
        self.assertIn('Если Контекст77Формы.Товар = Объект77Выбора Тогда', text)
        self.assertIn('Если Контекст77Формы.Товар = До77Выбора Тогда', text)
        self.assertNotIn('Контекст77Формы.Товар = Объект77Выбора;', text)
        self.assertNotIn('Контекст77Формы.Товар = До77Выбора;', text)
        self.assertNotIn('Если 1 Тогда', text)  # 7.7 requires a logical expression, not a number.
        save_only = text[text.index('Если Номер77Шага = -15 Тогда'):text.index('Если Номер77Шага = 2 Тогда')]
        self.assertIn('До77Выбора = Контекст77Формы.Товар;', save_only)
        self.assertNotIn('.Активизировать(', save_only)
        self.assertEqual(len({choice77.request(i, s) for i in range(1, 500) for s in range(1, 6)}), 499 * 5)

    def test_choice_context_and_result_are_read_back(self):
        self.assertEqual(scenario77.answer('choice-hwnd:123\r\nchoice-ready:1\r\nchoice-current:Имя\\n028'),
                         {'choice_hwnd': 123, 'choice_ready': 1, 'choice_current': 'Имя\r\n028'})
        final = trip(choice_result=1, choice_value='Имя')
        self.assertEqual(scenario77.merge_trips([trip(), final])['choice_result'], 1)

    def test_only_one_new_mdi_choice_is_accepted(self):
        data = windows()
        choice, issue = choice77.choice_window(data, {1, 2})
        self.assertIsNone(issue)
        self.assertEqual((choice['frame']['hwnd'], choice['dialog']['hwnd'], choice['list']['hwnd']), (3, 4, 5))
        for mutation in ('old', 'wrong', 'hidden', 'ambiguous', 'no-list'):
            changed, seen = copy.deepcopy(data), {1, 2}
            if mutation == 'old':
                seen.add(3)
            elif mutation == 'wrong':
                changed[2]['text'] = 'Другая форма'
            elif mutation == 'hidden':
                changed[4]['enabled'] = False
            elif mutation == 'ambiguous':
                changed.append(dict(changed[2], hwnd=6))
            else:
                changed.pop()
            with self.subTest(mutation=mutation):
                self.assertIsNotNone(choice77.choice_window(changed, seen)[1])

    def test_posting_enter_alone_does_not_confirm_selection(self):
        step = resolved({'choose': 'Товар', 'text': 'x'})[0]
        record = {'action': {'returned': True, 'choice': True}, 'round_trip': trip()}
        self.assertIn('reference was not verified', scenario77.judge(step, record, [], True))
        record['action']['choice_verified'] = True
        self.assertIsNone(scenario77.judge(step, record, [], True))
        record['action']['refused'] = 'the choice form did not close'
        self.assertIn('did not close', scenario77.judge(step, record, [], True))

    def test_dialog_keeps_choice_verification_on_the_final_step(self):
        first, last = resolved({'choose': 'Товар', 'text': 'x'}, {'dialog': 'Warning'})
        record = {'action': {'returned': True, 'choice': True}, 'modal': {'hwnd': 123}}
        self.assertIsNone(scenario77.judge(first, record, [], True))
        record = {'action': record['action'], 'window': {'hwnd': 123}, 'answer': {'requested': True}, 'round_trip': trip()}
        self.assertIn('reference was not verified', scenario77.judge(last, record, [], True))

    def test_insert_can_pass_its_open_choice_only_to_the_next_choose(self):
        watcher = form.FormWatcher.__new__(form.FormWatcher)
        watcher.pending_choice = None
        watcher.cancel_choice = lambda owned, chain: {'closed': True}
        owned = SimpleNamespace(inventory=windows)
        chain = SimpleNamespace(record={})
        watcher.unexpected_form(owned, chain, {'kind': 'add_row'}, {1, 2}, {'kind': 'choose'})
        self.assertEqual(watcher.pending_choice['frame']['hwnd'], 3)
        self.assertNotIn('refused', chain.record)
        chain = SimpleNamespace(record={})
        watcher.unexpected_form(owned, chain, {'kind': 'key'}, {1, 2}, {'kind': 'choose'})
        self.assertIn('unexpected nested form', chain.record['refused'])
        self.assertTrue(chain.record['nested_cleanup']['closed'])


if __name__ == '__main__':
    unittest.main()
