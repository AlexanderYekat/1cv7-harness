"""101: exact caption expectations on direct saved-document open and reopen."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import form_launcher77 as form
import form_window77 as window
import scenario77 as scenario

DESCRIPTION = {'controls': [
    {'id': 4152, 'identifier': 'Print', 'class': 'BUTTON', 'caption': 'Печать...'},
    {'id': 4153, 'identifier': 'Save', 'class': 'BUTTON', 'caption': 'Записать'},
    {'id': 4154, 'identifier': 'Field', 'class': '1CEDIT', 'caption': 'Поле'}]}


def profile(**changes):
    return dict({'form_object': 'Документ.СчетФактура', 'fixture_setup': 'Возврат 1;',
                 'fixture_verify': 'Возврат "read";', 'caption_control': 'Print', 'caption_text': 'Печать',
                 'steps': [{'check': 'Print', 'text': 'Печать'},
                           {'reopen': True, 'caption_control': 'Print', 'caption_text': 'Печать'}]}, **changes)


class DirectCaptionTests(unittest.TestCase):
    def select(self, parameters, description=DESCRIPTION):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        (base / '1Cv7.MD').write_bytes(b'metadata input')
        adapter = form.FormAdapter()
        adapter.commands(parameters, ['open', 'result', 'verify'])
        with patch.object(form, 'configuration_description', return_value=(description, {'path': 'document/form'})), \
                patch('harness77.metadata77.Metadata'):
            adapter.select_base(base, 'f' * 64)
        return adapter

    def test_direct_open_records_exact_expectation_without_mutating_the_description(self):
        original = copy.deepcopy(DESCRIPTION)
        adapter = self.select(profile())
        self.assertEqual(DESCRIPTION, original)
        self.assertEqual(adapter.form[0]['controls'][0]['caption'], 'Печать')
        self.assertEqual(adapter.form[0]['controls'][1:], original['controls'][1:])
        self.assertEqual(adapter.form[1]['runtime_caption_expectations'], {'Print': 'Печать'})
        self.assertIsNone(adapter.journal_form)
        self.assertIsNone(adapter.children_form)

    def test_other_captions_and_wrong_actual_text_still_fail(self):
        description = self.select(profile()).form[0]
        ids = window.window_ids(description)
        def inspect(print_text, save_text):
            return {'found': True, 'controls': [{'id': ids[4152], 'text': print_text},
                                                {'id': ids[4153], 'text': save_text}]}
        self.assertEqual(window.judge_captions(description, inspect('Печать', 'Записать')), [])
        self.assertIn('4152', window.judge_captions(description, inspect('Wrong', 'Записать'))[0])
        self.assertIn('4153', window.judge_captions(description, inspect('Печать', 'Wrong'))[0])

    def test_direct_caption_requires_pair_identifier_valid_text_and_verified_document(self):
        bad = [{'caption_control': None}, {'caption_text': 1}, {'caption_text': 'line\nbreak'},
               {'caption_text': '🙂'}, {'caption_control': '*'}, {'caption_control': 'Print.Text'},
               {'fixture_mode': 'journal_existing'}, {'fixture_mode': 'owner'},
               {'form_object': 'Справочник.Банки.ФормаЭлемента'}, {'fixture_verify': ''}]
        for change in bad:
            with self.subTest(change=change), self.assertRaises((ValueError, UnicodeEncodeError)):
                scenario.steps(profile(**change))
        for key in ('caption_control', 'caption_text'):
            p = profile(); p.pop(key)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                scenario.steps(p)

    def test_unknown_ambiguous_or_noncaption_control_is_refused_before_session(self):
        for name in ('Missing', 'Field'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'runtime caption'):
                self.select(profile(caption_control=name))
        duplicated = copy.deepcopy(DESCRIPTION)
        duplicated['controls'].append(dict(duplicated['controls'][0]))
        with self.assertRaisesRegex(ValueError, 'runtime caption'):
            self.select(profile(), duplicated)

    def test_explicit_reopen_caption_is_validated_before_session(self):
        p = profile()
        p['steps'][-1]['caption_control'] = 'Missing'
        with self.assertRaisesRegex(ValueError, 'runtime caption.*Missing'):
            self.select(p)
        p['steps'][-1].pop('caption_text')
        with self.assertRaisesRegex(ValueError, 'requires caption_control and caption_text'):
            scenario.steps(p)

    def test_initial_expectation_is_inherited_when_reopen_has_no_override(self):
        p = profile(); p['steps'][-1] = {'reopen': True}
        adapter = self.select(p)
        self.assertEqual(adapter.form[0]['controls'][0]['caption'], 'Печать')
        self.assertNotIn('caption_control', scenario.steps(p)[-1])
        code = adapter.controller(p)
        self.assertIn('ОткрытьФорму(Объект77Данных, Контекст77, 0)', code)
        self.assertNotIn('Harness77Журнал', code)

    def test_watcher_receives_permission_for_direct_button_reopen(self):
        adapter = self.select(profile())
        with tempfile.TemporaryDirectory() as temporary:
            adapter.run_dir = Path(temporary)
            (adapter.run_dir / 'form').mkdir()
            with patch.object(form, 'FormWatcher') as watcher:
                with adapter.watch(Path(temporary), {}, 'private-desktop'):
                    pass
                self.assertIs(watcher.call_args.kwargs['direct_existing'], True)


if __name__ == '__main__':
    unittest.main()
