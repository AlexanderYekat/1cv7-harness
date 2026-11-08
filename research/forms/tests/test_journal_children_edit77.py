"""044: handoff and return must keep exact child/source identities and saved state."""
import unittest
from unittest.mock import Mock, patch

import test_journal_children77 as legacy
from test_journal_children77 import BEFORE, SELECTED
import journal_children77 as children
import scenario77


class EditTests(unittest.TestCase):
    def profile(self, **changes):
        p = legacy.ChildrenTests().profile(limit=100, kinds='ПриходныйОрдер,СчетФактура',
            edit=True, expected_after='changed')
        p['steps'][-1].update(changes)
        p['steps'] += [dict(value='Сумма', text='75'), dict(reopen=True), dict(value='Сумма', text='75')]
        return p

    def test_edit_requires_explicit_after_state_mixed_kinds_and_verification(self):
        self.assertTrue(scenario77.steps(self.profile())[1]['edit'])
        for change in (dict(edit=False), dict(expected_after=''), dict(cancel=True), dict(empty=True)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                scenario77.steps(self.profile(**change))
        for remove in ('kinds', 'expected_after', 'edit'):
            p = self.profile(); p['steps'][1].pop(remove)
            with self.subTest(remove=remove), self.assertRaises(ValueError):
                scenario77.steps(p)
        p = self.profile(); p.pop('fixture_verify')
        with self.assertRaises(ValueError):
            scenario77.steps(p)

    def test_tail_requires_reopening_and_disallows_journal_commands(self):
        p = self.profile(); p['steps'] = p['steps'][:3]
        with self.assertRaisesRegex(ValueError, 'subsequent reopen'):
            scenario77.steps(p)
        for extra in (dict(journal_unpost=True, expected='changed'), dict(journal_copy=True)):
            p = self.profile(); p['steps'].append(extra)
            with self.assertRaises(ValueError):
                scenario77.steps(p)

    def test_legacy_read_only_does_not_admit_field_steps(self):
        p = legacy.ChildrenTests().profile(limit=100, kinds='ПриходныйОрдер,СчетФактура')
        p['steps'].append(dict(value='Сумма', text='50'))
        with self.assertRaisesRegex(ValueError, 'only journal commands'):
            scenario77.steps(p)

    def test_controller_reopens_selected_child_without_rebinding_source(self):
        items = scenario77.steps(self.profile())
        code = scenario77.step_function(items, journal_kind='ПриходныйОрдер')
        self.assertIn('ОткрытьФорму(Объект77Подготовки.ПолучитьЗначение(16), Контекст77, 0)', code)
        self.assertIn('Контекст77Формы.ТекущийДокумент() = Объект77Подготовки.ПолучитьЗначение(16)', code)
        self.assertIn('Контекст77Формы = Новый77Контекст;', code)
        self.assertIn('Если Номер77Шага <= -113000 Тогда Контекст77Формы = Новый77Контекст;', code)
        for forbidden in ('.Записать(', '.Провести(', 'Объект77Данных = Ссылка77;'):
            self.assertNotIn(forbidden, code)
        readonly = children.branches(dict(legacy.ACTION), 'ПриходныйОрдер')
        self.assertNotIn('Контекст77Формы = Новый77Контекст;', readonly)

    def returning(self):
        step = scenario77.steps(self.profile())[1]
        source = dict(chain=[dict(hwnd=10), dict(hwnd=11), dict(hwnd=30)])
        child = dict(chain=[dict(hwnd=41), dict(hwnd=40)])
        navigation = dict(before=BEFORE, step=step, source=source, children=dict(chain=[dict(hwnd=21),dict(hwnd=20)]),
                          children_frame=20, mdi=30, old_handles={10,11})
        opened = dict(SELECTED, journal_value='changed', journal_hwnd='41', journal_opened='1',
                      journal_kind='ПриходныйОрдер', journal_expected_kind='ПриходныйОрдер')
        returned = dict(opened, journal_hwnd='20')
        after = dict(BEFORE, journal_value='changed')
        watcher, form = Mock(), Mock()
        watcher.round_trip.side_effect = [opened, returned, after]
        form.alive.return_value = True
        form.inventory.return_value = [dict(hwnd=11,parent=30)]
        return watcher, form, child, navigation, [opened, returned, after]

    def test_return_closes_current_reopened_frame_then_list_and_preserves_source(self):
        watcher, form, child, nav, _ = self.returning()
        record = {}
        with patch.object(children, 'close_frame', return_value=dict(destroyed=True)) as close:
            self.assertIs(children.finish_edit(watcher, form, child, nav, record), nav['source'])
        self.assertEqual([c.args[2] for c in close.call_args_list], [40,20])
        self.assertTrue(record['return_verified'])
        self.assertEqual([c.args[0] for c in watcher.round_trip.call_args_list], [-112002,-111902,-113002])

    def test_return_never_closes_unverified_document(self):
        for change in (dict(journal_id='other'), dict(journal_link_id='other'), dict(journal_kind='СчетФактура'),
                       dict(journal_value='unchanged'), dict(journal_hwnd='20'), dict(complete=False),
                       dict(journal_opened='0')):
            watcher, form, child, nav, trips = self.returning()
            trips[0].update(change); watcher.round_trip.side_effect = trips
            with self.subTest(change=change), patch.object(children, 'close_frame') as close:
                with self.assertRaises(RuntimeError):
                    children.finish_edit(watcher, form, child, nav, {})
                close.assert_not_called()

    def test_return_rejects_changed_list_source_extra_frame_and_missing_form(self):
        for mode in ('list', 'source', 'extra', 'missing'):
            watcher, form, child, nav, trips = self.returning()
            if mode == 'list': trips[1]['journal_link'] = '0'
            if mode == 'source': trips[2]['journal_id'] = 'neighbor'
            if mode == 'extra': form.inventory.return_value += [dict(hwnd=99,parent=30)]
            if mode == 'missing': form.alive.return_value = False
            with self.subTest(mode=mode), patch.object(children, 'close_frame', return_value=dict(destroyed=True)):
                with self.assertRaises(RuntimeError):
                    children.finish_edit(watcher, form, child, nav, {})

    def test_watcher_uses_handed_off_controls_and_reports_failed_return(self):
        from pathlib import Path
        from form_launcher77 import FormWatcher
        description = dict(controls=[dict(id=4152, identifier='Комментарий', caption='', **{'class':'1CEDIT'})])
        initial = dict(chain=[dict(hwnd=10)], controls=[dict(id=4152,hwnd=11)])
        document = dict(chain=[dict(hwnd=20)], controls=[dict(id=4152,hwnd=21)])
        steps = [dict(index=1,kind='journal_children',edit=True,target='journal_children'),
                 dict(index=2,kind='check',target='Комментарий',record_id=4152,element_class='1CEDIT',expect='text',text='saved')]
        watcher = FormWatcher(Path('.'),{'run_id':'test'},'private',description,[],Path('.'),steps=steps,
                              created_description=description)
        watcher.round_trip = Mock(return_value=dict(returned=True,complete=True,diagnostics=[],messages=[]))
        owned = Mock()
        owned.alive.return_value = True
        owned.element_state.return_value = dict(text='saved')
        def handoff(watcher, form, inspection, step, record):
            return document, dict(opening=record)
        with patch.object(children,'execute',side_effect=handoff), patch.object(children,'finish_edit',return_value=initial):
            records = watcher.run_steps(owned,initial)
        self.assertEqual(owned.element_state.call_args.args[0]['hwnd'],21)
        self.assertTrue(all(r['status']=='passed' for r in records))
        with patch.object(children,'execute',side_effect=handoff), patch.object(children,'finish_edit',side_effect=RuntimeError('foreign reference')):
            records = watcher.run_steps(owned,initial)
        self.assertEqual(records[-1]['status'],'failed')
        self.assertIn('foreign reference',records[-1]['issue'])

    def test_posted_enter_waits_for_new_owned_visible_frame(self):
        watcher, form = Mock(), Mock()
        watcher.stopped.wait.return_value = False
        old = [dict(hwnd=10,parent=30,visible=True,enabled=True)]
        new = dict(hwnd=20,parent=30,visible=True,enabled=True)
        form.inventory.side_effect = [old,old+[dict(new,visible=False)],old+[new]]
        record = {}
        self.assertEqual(children.opened_frame(watcher,form,30,old,record),20)
        self.assertEqual(record['opened_window_polls'],3)
        self.assertEqual(watcher.stopped.wait.call_count,2)

    def test_opened_frame_wait_rejects_ambiguity_and_cancellation(self):
        watcher, form = Mock(), Mock()
        watcher.stopped.wait.return_value = True
        new = dict(hwnd=20,parent=30,visible=True,enabled=True)
        for inventory in ([],[dict(new,parent=99)],[new,dict(new,hwnd=21)]):
            form.inventory.return_value = inventory
            with self.subTest(inventory=inventory), self.assertRaises(RuntimeError):
                children.opened_frame(watcher,form,30,[],{})

    def test_opening_handler_busy_text_read_is_bounded_and_other_errors_propagate(self):
        watcher, form = Mock(), Mock()
        watcher.stopped.wait.return_value = False
        form.inventory.side_effect = [RuntimeError('owned window text did not respond'),
            [dict(hwnd=20,parent=30,visible=True,enabled=True)]]
        record = {}
        self.assertEqual(children.opened_frame(watcher,form,30,[],record),20)
        self.assertEqual(record['opened_window_busy'],['owned window text did not respond'])
        form.inventory.side_effect = RuntimeError('foreign thread')
        with self.assertRaisesRegex(RuntimeError,'foreign thread'):
            children.opened_frame(watcher,form,30,[],{})


if __name__ == '__main__':
    unittest.main()
