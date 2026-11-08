"""046: read-only handoff, exact tab matching and acknowledged native navigation."""
import copy
import importlib.util
from pathlib import Path
import unittest
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scenario77
import tabs77

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('tabs_example', ROOT / 'examples/form-tabs/prepare.py')
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class TabsTests(unittest.TestCase):
    def parameters(self, case='success'):
        import tomllib
        return tomllib.loads(example.case_scenario(case))['platform']['parameters']

    def test_browse_rejects_mutations_and_mixed_edit_mode(self):
        parsed = scenario77.steps(self.parameters())
        self.assertTrue(parsed[2]['browse'])
        for extra in (dict(input='Комментарий', text='x'), dict(click='Записать'), dict(reopen=True),
                      dict(key='Insert'), dict(cell='Сумма', text='75'), dict(close_form=True), dict(row=1)):
            p = self.parameters(); p['steps'].append(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                scenario77.steps(p)
        for option in (dict(browse=False), dict(edit=True), dict(expected_after='changed'), dict(cancel=True)):
            p = self.parameters(); p['steps'][2].update(option)
            with self.subTest(option=option), self.assertRaises(ValueError):
                scenario77.steps(p)

    def test_browse_requires_verification_and_tab_tail(self):
        for remove in ('fixture_verify',):
            p=self.parameters(); p.pop(remove)
            with self.assertRaises(ValueError): scenario77.steps(p)
        p=self.parameters(); p['steps']=p['steps'][:3]
        with self.assertRaisesRegex(ValueError,'tab steps'): scenario77.steps(p)

    def test_controller_reads_child_table_only_after_handoff(self):
        items=scenario77.steps(self.parameters())
        items=scenario77.resolve(items, dict(controls=[], browser=dict(document=True, fields=[dict(identifier='Сумма',caption='Сумма',**{'class':'1CEDIT'},type='N')])) )
        text=scenario77.step_function(items,table=True,journal_kind='СчетФактура')
        self.assertIn('Если (Номер77Шага >= 3) Тогда',text)
        self.assertIn('Контекст77Формы = Новый77Контекст;',text)
        self.assertIn('Контекст77Формы.ВыгрузитьТабличнуюЧасть(Таблица77, "Сумма");',text)
        self.assertNotIn('.Записать(',text)

    def test_exact_caption_refuses_missing_ambiguous_and_invalid_selection(self):
        self.assertEqual(tabs77.target(dict(items=['Шапка','&Табличная часть'],selected=0),'табличная часть'),1)
        for state, caption in ((dict(items=['Шапка'],selected=0),'нет'),
                               (dict(items=['Шапка','шапка'],selected=0),'Шапка'),
                               (dict(items=['Шапка'],selected=-1),'Шапка')):
            with self.subTest(state=state), self.assertRaises(RuntimeError): tabs77.target(state,caption)

    def native(self):
        window=dict(hwnd=42,**{'class':'SysTabControl32'},parent=20,visible=True,enabled=True)
        state=dict(window=window,frame=20,items=['Шапка','Табличная часть'],selected=0,caption='Шапка')
        inspection=dict(found=True,chain=[dict(hwnd=10),dict(hwnd=20),dict(hwnd=30,**{'class':'MDIClient'})],
                        controls=[dict(id=4151,hwnd=50,visible=True)])
        watcher,form=Mock(),Mock()
        watcher.round_trip.return_value=dict(returned=True,complete=True,diagnostics=[])
        form.give_focus.return_value=dict(hwnd=42)
        form.post_key.return_value=dict(returned=True)
        form.inspect.return_value=inspection
        after=dict(state,selected=1,caption='Табличная часть')
        return watcher,form,inspection,state,after

    def test_native_navigation_reads_again_after_each_acknowledged_key(self):
        watcher,form,inspection,before,after=self.native(); record={}
        with patch.object(tabs77,'read',side_effect=[before,after]):
            tabs77.execute(watcher,form,inspection,dict(index=4,target='Табличная часть',browser_visible=True),record)
        self.assertTrue(record['tab_verified'])
        self.assertEqual(len(record['tab_keys']),1)
        self.assertEqual(form.post_key.call_args.args,(42,'Right',0x27,True))

    def test_missing_tab_sends_no_keys(self):
        watcher,form,inspection,before,after=self.native()
        with patch.object(tabs77,'read',return_value=before), self.assertRaises(RuntimeError):
            tabs77.execute(watcher,form,inspection,dict(index=4,target='нет'),{})
        form.post_key.assert_not_called(); watcher.round_trip.assert_not_called()

    def test_same_tab_sends_no_keys_but_checks_form_and_visibility(self):
        watcher,form,inspection,before,after=self.native(); record={}
        with patch.object(tabs77,'read',return_value=before):
            tabs77.execute(watcher,form,inspection,dict(index=4,target='Шапка'),record)
        form.post_key.assert_not_called(); self.assertTrue(record['tab_verified'])

    def test_refuses_no_motion_wrong_window_response_error_and_hidden_table(self):
        for mode in ('no-motion','wrong-window','reply','hidden','identity'):
            watcher,form,inspection,before,after=self.native()
            if mode=='no-motion': after=before
            if mode=='wrong-window': after=copy.deepcopy(after); after['window']['hwnd']=99
            if mode=='reply': watcher.round_trip.return_value['complete']=False
            if mode=='hidden': inspection['controls'][0]['visible']=False
            if mode=='identity': form.inspect.return_value=dict(inspection,chain=[dict(hwnd=99)])
            with self.subTest(mode=mode), patch.object(tabs77,'read',side_effect=[before,after]), self.assertRaises(RuntimeError):
                tabs77.execute(watcher,form,inspection,dict(index=4,target='Табличная часть',browser_visible=True),{})


if __name__=='__main__': unittest.main()
