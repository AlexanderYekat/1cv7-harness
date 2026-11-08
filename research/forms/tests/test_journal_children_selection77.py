"""042: bounded navigation, exact reference, and a fresh pre-Enter gate."""
import unittest
from unittest.mock import Mock, patch

from test_journal_children77 import ACTION, BEFORE, SELECTED
import test_journal_children77 as legacy
import journal_children77 as children
import scenario77


class SelectionTests(unittest.TestCase):
    def search(self, trips, limit=100):
        form = Mock()
        form.post_key.return_value = dict(returned=True)
        call = Mock(side_effect=trips)
        record = {}
        result = children.search_child(form, dict(hwnd=22), BEFORE, [20], dict(ACTION, limit=limit), record, call)
        return result, form, record, call

    def test_profile_requires_bounded_integer_and_rejects_empty_search(self):
        profile = legacy.ChildrenTests().profile(limit=100)
        self.assertEqual(scenario77.steps(profile)[-1]['limit'], 100)
        for change in (dict(limit=0), dict(limit=101), dict(limit=True), dict(limit=1.5), dict(limit=2, empty=True)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                scenario77.steps(legacy.ChildrenTests().profile(**change))

    def test_second_navigation_pair_cannot_reuse_raw_answer_numbers(self):
        profile = legacy.ChildrenTests().profile(limit=100)
        profile['steps'] = profile['steps'] + profile['steps']
        with self.assertRaises(ValueError):
            scenario77.steps(profile)

    def test_first_middle_last_stop_at_exact_reference_and_recheck(self):
        for position in (1, 2, 3):
            with self.subTest(position=position):
                trips = [dict(SELECTED, journal_match='0', journal_id=f'neighbor-{n}') for n in range(position-1)]
                trips += [dict(SELECTED, elapsed_s=.1), dict(SELECTED, elapsed_s=.2)]
                result, form, record, call = self.search(trips, limit=position)
                self.assertEqual(result['journal_id'], 'child')
                self.assertEqual([c.args[1] for c in form.post_key.call_args_list], ['End'] + ['Up']*(position-1))
                self.assertEqual([c.args[0] for c in call.call_args_list], [-111001-i for i in range(position)]+[-111900])
                self.assertEqual(len(record['child_search']), position)
                self.assertNotIn('open_action', record)

    def test_limit_never_sends_an_extra_key_or_enter(self):
        form = Mock(); form.post_key.return_value = dict(returned=True)
        call = Mock(return_value=dict(SELECTED, journal_id='neighbor', journal_match='0'))
        record = {}
        with self.assertRaisesRegex(RuntimeError, 'search limit'):
            children.search_child(form, dict(hwnd=22), BEFORE, [20], dict(ACTION, limit=1), record, call)
        self.assertEqual(form.post_key.call_count, 1)
        self.assertEqual(call.call_count, 1)

    def test_missing_target_stops_on_repeated_boundary(self):
        neighbor = dict(SELECTED, journal_id='neighbor', journal_match='0')
        form = Mock(); form.post_key.return_value = dict(returned=True)
        call = Mock(side_effect=[neighbor, neighbor])
        with self.assertRaisesRegex(RuntimeError, 'not found at list boundary'):
            children.search_child(form, dict(hwnd=22), BEFORE, [20], dict(ACTION, limit=100), {}, call)
        self.assertEqual(form.post_key.call_count, 2)

    def test_bad_candidate_fails_before_next_key(self):
        for change in (dict(journal_source_id='other'), dict(journal_link_id='other'), dict(journal_link='0'),
                       dict(journal_expected_id=''), dict(journal_id=''), dict(journal_match='1'),
                       dict(journal_hwnd='10'), dict(journal_value='changed'), dict(journal_empty='1'),
                       dict(returned=False), dict(complete=False), dict(diagnostics=['error'])):
            trip = dict(dict(SELECTED, journal_match='0', journal_id='neighbor'), **change)
            form = Mock(); form.post_key.return_value = dict(returned=True)
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                children.search_child(form, dict(hwnd=22), BEFORE, [20], dict(ACTION, limit=100), {}, Mock(return_value=trip))
            self.assertEqual(form.post_key.call_count, 1)

    def test_changed_target_during_search_is_rejected_even_if_next_match_is_true(self):
        trips = [dict(SELECTED, journal_id='neighbor', journal_match='0'),
                 dict(SELECTED, journal_id='other', journal_expected_id='other')]
        with self.assertRaisesRegex(RuntimeError, 'expected reference changed'):
            self.search(trips)

    def test_changed_selection_before_enter_is_rejected(self):
        for change in (dict(journal_id='other', journal_expected_id='other'),
                       dict(journal_id='other', journal_match='0'), dict(journal_value='changed'),
                       dict(journal_hwnd='10'), dict(journal_comment='changed')):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                self.search([SELECTED, dict(SELECTED, **change)])

    def test_cancel_after_multiline_search_closes_list_without_enter(self):
        watcher, form = Mock(), Mock()
        watcher.round_trip.side_effect = [BEFORE, dict(SELECTED, journal_id='neighbor', journal_match='0'),
                                           SELECTED, SELECTED, BEFORE]
        watcher.children_description = dict(form=dict(caption='Общий журнал'))
        old = [dict(hwnd=10, parent=11), dict(hwnd=11, parent=30)]
        form.inventory.side_effect = [old, old + [dict(hwnd=20,parent=30,visible=True,enabled=True,
                                                     text='Общий журнал source caption')], old]
        form.post_key.return_value = dict(returned=True)
        inspected = dict(chain=[dict(hwnd=21), dict(hwnd=20)], controls=[dict(id=4151, hwnd=22)])
        pending = Mock(outcome=dict(returned=True)); pending.done.return_value = True
        record = {}
        with patch('journal77.native_menu', return_value=dict(enabled=True)), \
             patch('form_window77.Pending', return_value=pending), \
             patch.object(children, 'inspect_frame', return_value=inspected), \
             patch.object(children, 'close_frame', return_value=dict(destroyed=True)) as close:
            children.execute(watcher, form, dict(chain=[dict(hwnd=10), dict(hwnd=11), dict(hwnd=30)]),
                             dict(ACTION, index=3, limit=100, cancel=True), record)
        self.assertTrue(record['return_verified'])
        self.assertEqual([c.args[1] for c in form.post_key.call_args_list], ['End', 'Up'])
        self.assertNotIn('open_action', record)
        close.assert_called_once_with(watcher, form, 20)


if __name__ == '__main__':
    unittest.main()
