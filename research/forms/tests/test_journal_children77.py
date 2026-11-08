"""041: exact identity gates before native dispatch, Enter, and read-only return."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import journal_children77 as children
import scenario77
from test_journal_existing77 import parameters

ACTION = dict(journal_children=True, source='РасходнаяНакладная', link='ДокументОснование', reference=16,
              journal='Журнал.Общий.ФормаСписка.ФормаСписка', expected='unchanged')
BEFORE = dict(returned=True, complete=True, diagnostics=[], journal_value='unchanged', journal_id='source',
              journal_current='source caption', journal_match='1', journal_posted='0', journal_deleted='0', journal_hwnd='10')
SELECTED = dict(returned=True, complete=True, diagnostics=[], journal_value='unchanged', journal_id='child',
                journal_source_id='source', journal_expected_id='child', journal_link_id='source',
                journal_link='1', journal_match='1', journal_empty='0', journal_hwnd='20')


class ChildrenTests(unittest.TestCase):
    def profile(self, **changes):
        return parameters(form_object='Документ.ПриходныйОрдер', steps=[dict(find_document=True, open=False),
                          dict(ACTION, **changes)])

    def test_requires_exact_preceding_cursor_and_explicit_contract(self):
        self.assertEqual(scenario77.steps(self.profile())[-1]['kind'], 'journal_children')
        for change in (dict(source=''), dict(link='x.y'), dict(reference=101), dict(reference=0), dict(expected=''),
                       dict(journal='Журнал.Общий'), dict(empty=True, cancel=True), dict(caption_control='x')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                scenario77.steps(self.profile(**change))
        for steps in ([ACTION], [dict(find_document=True), ACTION],
                      [dict(find_document=True, open=False), ACTION, ACTION]):
            p = self.profile(); p['steps'] = steps
            with self.assertRaises(ValueError):
                scenario77.steps(p)

    def test_fixture_context_validates_the_source_kind_before_opening_the_child_kind(self):
        import fixture77
        profile = self.profile()
        metadata = Mock()
        metadata.objects.return_value = {'Документ': {'расходнаянакладная': {}, 'приходныйордер': {}}}
        settings = fixture77.options(profile, profile['form_object'])
        context = fixture77.context(profile['form_object'], settings, metadata)
        self.assertEqual(context, dict(type='Документ', kind='РасходнаяНакладная', group=0))

    def test_rejects_wrong_identity_state_or_incomplete_response(self):
        children.checked_child(SELECTED, BEFORE, [20])
        for change in (dict(journal_match='0'), dict(journal_id='same caption different id'),
                       dict(journal_source_id='neighbor'), dict(journal_link_id='neighbor'), dict(journal_link='0'),
                       dict(journal_hwnd='10'), dict(journal_value='changed'), dict(journal_empty='1'),
                       dict(returned=False), dict(complete=False), dict(diagnostics=['error']),
                       dict(journal_error='error'), dict(journal_expected_id='')):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                children.checked_child(dict(SELECTED, **change), BEFORE, [20])

    def test_open_requires_separate_saved_context_confirmation(self):
        with self.assertRaises(RuntimeError):
            children.checked_child(SELECTED, BEFORE, [20], opened=True)
        children.checked_child(dict(SELECTED, journal_opened='1'), BEFORE, [20], opened=True)

    def test_empty_has_distinct_no_match_contract(self):
        empty = dict(SELECTED, journal_empty='1', journal_match='0')
        children.checked_child(empty, BEFORE, [20], empty=True)
        for change in (dict(journal_empty='0'), dict(journal_match='1'), dict(journal_value='changed')):
            with self.assertRaises(RuntimeError):
                children.checked_child(dict(empty, **change), BEFORE, [20], empty=True)

    def test_raw_duplicate_and_unknown_fields_fail_closed(self):
        for value in ('journal-id:a\njournal-id:b', 'journal-source-id:a\njournal-source-id:b',
                      'journal-expected-id:a\njournal-unknown:a'):
            self.assertIn('journal_error', scenario77.answer(value))
        self.assertEqual(scenario77.answer('journal-id:ref\njournal-empty:0'), dict(journal_id='ref', journal_empty='0'))

    def test_changed_source_blocks_command_before_menu_access(self):
        watcher, form = Mock(), Mock()
        watcher.round_trip.return_value = dict(BEFORE, journal_value='changed')
        with self.assertRaises(RuntimeError):
            children.execute(watcher, form, dict(chain=[dict(hwnd=10), dict(hwnd=11)]),
                             dict(ACTION, index=3), {})
        form.inventory.assert_not_called()
        form.send.assert_not_called()

    def test_disabled_command_is_never_dispatched(self):
        watcher, form = Mock(), Mock()
        watcher.round_trip.return_value = BEFORE
        with patch('journal77.native_menu', return_value=dict(enabled=False)), \
             patch('form_window77.Pending') as pending:
            with self.assertRaises(RuntimeError):
                children.execute(watcher, form, dict(chain=[dict(hwnd=10), dict(hwnd=11)]),
                                 dict(ACTION, index=3), {})
        pending.assert_not_called()
        form.inventory.assert_not_called()

    def test_cancel_and_empty_return_to_source_without_enter(self):
        for empty in (False, True):
            watcher, form = Mock(), Mock()
            selected = dict(SELECTED, journal_empty='1', journal_match='0') if empty else SELECTED
            watcher.round_trip.side_effect = [BEFORE, selected, selected, BEFORE]
            watcher.children_description = dict(form=dict(caption='Общий журнал'))
            old = [dict(hwnd=10, parent=11), dict(hwnd=11, parent=30)]
            form.inventory.side_effect = [old, old + [dict(hwnd=20,parent=30,visible=True,enabled=True,
                                                       text='Общий журнал source caption')], old]
            form.post_key.return_value = dict(returned=True)
            opened = dict(chain=[dict(hwnd=21), dict(hwnd=20)], controls=[dict(id=4151, hwnd=22)])
            pending = Mock(outcome=dict(returned=True)); pending.done.return_value = True
            record = {}
            with patch('journal77.native_menu', return_value=dict(enabled=True)), \
                 patch('form_window77.Pending', return_value=pending), \
                 patch.object(children, 'inspect_frame', return_value=opened), \
                 patch.object(children, 'close_frame', return_value=dict(destroyed=True)):
                children.execute(watcher, form, dict(chain=[dict(hwnd=10), dict(hwnd=11), dict(hwnd=30)]),
                                 dict(ACTION, index=3, empty=empty, cancel=not empty), record)
            self.assertTrue(record['return_verified'])
            self.assertEqual([c.args[1] for c in form.post_key.call_args_list], ['End', 'Up'])
            self.assertNotIn('open_action', record)

    def test_foreign_child_blocks_enter_and_closes_only_its_new_frame(self):
        watcher, form = Mock(), Mock()
        watcher.round_trip.side_effect = [BEFORE, dict(SELECTED, journal_match='0')]
        watcher.children_description = dict(form=dict(caption='Общий журнал'))
        form.inventory.side_effect = [[dict(hwnd=10)], [dict(hwnd=20, parent=30, visible=True, enabled=True,
                                                    text='Общий журнал source caption')]]
        form.post_key.return_value = dict(returned=True)
        opened = dict(chain=[dict(hwnd=21), dict(hwnd=20)], controls=[dict(id=4151, hwnd=22)])
        pending = Mock(outcome=dict(returned=True)); pending.done.return_value = True
        with patch('journal77.native_menu', return_value=dict(enabled=True)), \
             patch('form_window77.Pending', return_value=pending), \
             patch.object(children, 'inspect_frame', return_value=opened), \
             patch.object(children, 'close_frame', return_value=dict(destroyed=True)) as close:
            with self.assertRaises(RuntimeError):
                children.execute(watcher, form, dict(chain=[dict(hwnd=10), dict(hwnd=11), dict(hwnd=30)]),
                                 dict(ACTION, index=3), {})
        self.assertEqual(form.post_key.call_count, 1)
        self.assertEqual(form.post_key.call_args.args[1], 'End')
        close.assert_called_once_with(watcher, form, 20)

    def test_controller_navigation_is_read_only(self):
        text = children.branches(ACTION, 'ПриходныйОрдер')
        for prohibited in ('.Записать(', '.Провести(', '.ОткрытьФорму(', '.ПодчинениеДокументу(', '.АктивизироватьОбъект('):
            self.assertNotIn(prohibited, text)
        self.assertIn('Harness77КодСсылки', text)
        self.assertIn('ЗначениеВСтрокуВнутр(Док77Кода.ТекущийДокумент())', children.reference_function())
        self.assertIn('Новый77Контекст.ДокументОснование <> Объект77Данных', text)

    def test_scoped_inspection_disambiguates_identical_control_ids(self):
        from form_window77 import OwnedForm
        fake = Mock()
        def window(hwnd, parent, id_=0, class_='#32770'):
            return dict(hwnd=hwnd, parent=parent, id=id_, text='', visible=True, enabled=True, **{'class': class_})
        fake.inventory.return_value = [window(1, None, class_='main'), window(2, 1, class_='MDIClient'),
            window(10, 2, class_='frame'), window(11, 10), window(12, 11, 4151),
            window(20, 2, class_='frame'), window(21, 20), window(22, 21, 4151)]
        fake.dpi.return_value = 96
        fake.client_size.return_value = [100, 100]
        fake.rect_in_parent.return_value = [0, 0, 10, 10]
        self.assertFalse(OwnedForm.inspect(fake, [4151])['found'])
        scoped = OwnedForm.inspect(fake, [4151], frame=20)
        self.assertTrue(scoped['found'])
        self.assertEqual(scoped['controls'][0]['hwnd'], 22)
        self.assertEqual(scoped['chain'][1]['hwnd'], 20)
        self.assertFalse(OwnedForm.inspect(fake, [4151], frame=999)['found'])

    def test_browse_must_be_visible_owned_shape_inside_the_frame(self):
        import copy
        form = Mock()
        original = dict(found=True, chain=[dict(hwnd=1,client_size=[100,100]),dict(hwnd=2)],
                        controls=[dict(id=4151,rect=[3,3,80,60],visible=True,enabled=True,**{'class':'browse'})])
        description = dict(browser=dict(position=0, columns=0), controls=[])
        with patch('form_window77.expected_geometry', return_value={}), \
             patch('form_window77.fit_units', return_value=dict(consistent=True)), \
             patch('form_window77.judge_layout', return_value=[]), patch('form_window77.judge_captions', return_value=[]):
            form.inspect.return_value = copy.deepcopy(original)
            children.inspect_frame(form, description, 2)
            for change in (dict(rect=[999,999,1,1]), dict(visible=False), dict(enabled=False),
                           dict(rect=[3,3,0,0]), {'class':'Static'}):
                altered = copy.deepcopy(original)
                altered['controls'][0].update(change)
                form.inspect.return_value = altered
                with self.assertRaises(RuntimeError):
                    children.inspect_frame(form, description, 2)


if __name__ == '__main__':
    unittest.main()
