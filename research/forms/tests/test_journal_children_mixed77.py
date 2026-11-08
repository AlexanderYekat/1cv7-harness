"""043: heterogeneous rows cannot weaken exact identity and kind checks."""
import unittest
from unittest.mock import Mock, patch

import test_journal_children77 as legacy
from test_journal_children77 import SELECTED, BEFORE
import journal_children77 as children
import scenario77

KINDS = 'ПриходныйОрдер,СчетФактура'


class MixedTests(unittest.TestCase):
    def step(self, **changes):
        profile = legacy.ChildrenTests().profile(limit=100, kinds=KINDS, **changes)
        return scenario77.steps(profile)[-1]

    def search(self, trips, step=None):
        form = Mock()
        form.post_key.return_value = dict(returned=True)
        record = {}
        children.search_child(form, dict(hwnd=22), BEFORE, [20], step or self.step(), record, Mock(side_effect=trips))
        return form, record

    def test_explicit_kinds_need_distinct_valid_names_target_and_limit(self):
        step = self.step()
        self.assertEqual(step['kinds'], KINDS.split(','))
        self.assertEqual(step['target_kind'], 'ПриходныйОрдер')
        for kinds in ('', 'ПриходныйОрдер', KINDS+',', KINDS+',счетфактура',
                      'ПриходныйОрдер,РасходнаяНакладная', 'X,СчетФактура', 'ПриходныйОрдер,X.Y',
                      'ПриходныйОрдер,'+','.join('X'+str(n) for n in range(10)), [KINDS]):
            with self.subTest(kinds=kinds), self.assertRaises(ValueError):
                profile = legacy.ChildrenTests().profile(limit=100, kinds=kinds)
                scenario77.steps(profile)
        with self.assertRaises(ValueError):
            scenario77.steps(legacy.ChildrenTests().profile(kinds=KINDS))

    def test_preflight_checks_link_on_every_declared_kind(self):
        metadata = Mock()
        metadata.objects.return_value = {'Документ': {'приходныйордер': {}, 'счетфактура': {}}}
        field = Mock(code='O', kind=None)
        metadata.attributes.return_value = {'документоснование': field}
        children.validate_metadata(metadata, 'Документ.ПриходныйОрдер', self.step())
        self.assertEqual(metadata.attributes.call_count, 2)
        for attrs in ({}, {'документоснование': Mock(code='S', kind=None)},
                      {'документоснование': Mock(code='O', kind='Другой')}):
            metadata.attributes.side_effect = [{'документоснование': field}, attrs]
            with self.subTest(attrs=attrs), self.assertRaises(ValueError):
                children.validate_metadata(metadata, 'Документ.ПриходныйОрдер', self.step())
        metadata.objects.return_value = {'Документ': {'приходныйордер': {}}}
        metadata.attributes.side_effect = None
        with self.assertRaisesRegex(ValueError, 'unknown child kind'):
            children.validate_metadata(metadata, 'Документ.ПриходныйОрдер', self.step())

    def trip(self, **changes):
        return dict(dict(SELECTED, journal_kind='ПриходныйОрдер', journal_expected_kind='ПриходныйОрдер'), **changes)

    def test_search_crosses_other_kind_and_similar_same_kind(self):
        trips = [self.trip(journal_id='invoice', journal_kind='СчетФактура', journal_match='0'),
                 self.trip(journal_id='similar order', journal_match='0'), self.trip(), self.trip()]
        form, record = self.search(trips)
        self.assertEqual([c.args[1] for c in form.post_key.call_args_list], ['End', 'Up', 'Up'])
        self.assertEqual(record['selected_child']['journal_id'], 'child')

    def test_can_select_the_second_kind_after_crossing_the_first(self):
        step = self.step()
        step['target_kind'] = 'СчетФактура'
        first = self.trip(journal_id='order', journal_match='0', journal_expected_kind='СчетФактура')
        selected = self.trip(journal_kind='СчетФактура', journal_expected_kind='СчетФактура')
        self.search([first, selected, selected], step)

    def test_unknown_missing_or_wrong_target_kind_blocks_search(self):
        for change in (dict(journal_kind='Другой'), dict(journal_kind=''), dict(journal_expected_kind='СчетФактура'),
                       dict(journal_kind='СчетФактура')):
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, 'kind differs'):
                self.search([self.trip(**change), self.trip()])

    def test_fresh_recheck_and_opened_context_require_target_kind(self):
        with self.assertRaisesRegex(RuntimeError, 'kind differs'):
            self.search([self.trip(), self.trip(journal_kind='СчетФактура')])
        with self.assertRaisesRegex(RuntimeError, 'kind differs'):
            children.checked_kind(self.trip(journal_kind='СчетФактура'), self.step(), target=True)

    def test_controller_reads_dynamic_saved_kind_but_keeps_expected_kind_gate(self):
        code = children.branches(self.step(), 'ПриходныйОрдер')
        self.assertIn('СоздатьОбъект("Документ." + Ссылка77.Вид())', code)
        self.assertIn('Ожидаемая77Ссылка.Вид() <> "ПриходныйОрдер"', code)
        self.assertIn('(Ссылка77.Вид() = "СчетФактура")', code)
        self.assertIn('journal-expected-kind:', code)
        for forbidden in ('.Записать(', '.Новый(', '.Провести(', '.ПодчинениеДокументу(', '.ОткрытьФорму('):
            self.assertNotIn(forbidden, code)
        self.assertNotIn('journal-kind:', children.branches(dict(legacy.ACTION), 'ПриходныйОрдер'))

    def test_raw_kind_fields_reject_duplicates(self):
        for field in ('journal-kind', 'journal-expected-kind'):
            self.assertIn('journal_error', scenario77.answer(f'{field}:A\n{field}:B'))
        self.assertEqual(scenario77.answer('journal-kind:A\njournal-expected-kind:B'),
                         dict(journal_kind='A', journal_expected_kind='B'))

    def test_invoice_runtime_expectations_are_explicit_and_scoped(self):
        description = dict(controls=[dict(identifier='Print', caption='Print...', formula='Print()', **{'class': 'BUTTON'})],
                           browser=dict(position=0))
        step = self.step(caption_control='Print', caption_text='Print', browser_visible=False)
        changed = children.runtime_description(description, step)
        self.assertEqual(changed['controls'][0]['caption'], 'Print')
        self.assertIs(changed['browser']['expected_visible'], False)
        self.assertEqual(description['controls'][0]['caption'], 'Print...')
        self.assertNotIn('expected_visible', description['browser'])
        with self.assertRaises(ValueError):
            children.runtime_description(dict(controls=description['controls']), step)
        with self.assertRaises(ValueError):
            scenario77.steps(legacy.ChildrenTests().profile(browser_visible=False))
        step['caption_control'] = 'Missing'
        with self.assertRaises(ValueError):
            children.runtime_description(description, step)

    def test_hidden_browser_requires_exact_explicit_visibility_and_keeps_geometry_checks(self):
        import copy
        description = dict(browser=dict(position=0, columns=0, expected_visible=False), controls=[])
        opened = dict(found=True, chain=[dict(hwnd=1,client_size=[100,100]),dict(hwnd=2)],
                      controls=[dict(id=4151,rect=[3,3,80,60],visible=False,enabled=True,**{'class':'browse'})])
        form = Mock()
        with patch('form_window77.expected_geometry', return_value={}), \
             patch('form_window77.fit_units', return_value=dict(consistent=True)), \
             patch('form_window77.judge_layout', return_value=[]), patch('form_window77.judge_captions', return_value=[]):
            form.inspect.return_value = copy.deepcopy(opened)
            children.inspect_frame(form, description, 2)
            for change in (dict(rect=[999,999,1,1]), dict(visible=True), dict(enabled=False), {'class':'Static'}):
                broken = copy.deepcopy(opened)
                broken['controls'][0].update(change)
                form.inspect.return_value = broken
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    children.inspect_frame(form, description, 2)


if __name__ == '__main__':
    unittest.main()
