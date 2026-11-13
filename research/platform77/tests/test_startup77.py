"""091: debugger-list repair, exact binding evidence and startup observations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proxy_debug77 import observer_binding, prepare_observer
from startup77 import StartupTrace, command_marker, commands_processed


class StartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name)
        self.id = str(uuid4())

    def binding(self, row='10 e 75fb7b30 0001 (0001) 0:**** combase!CoRegisterClassObject "callback"'):
        return ('HARNESS77_OBSERVER_BOUND_BEGIN:' + self.id + '\n0:000> bl 10\n' + row
                + '\nHARNESS77_OBSERVER_BOUND_END:' + self.id + '\n')

    def test_refresh_precedes_binding_and_bound_proof(self):
        commands, nonce = prepare_observer(self.out, self.id)
        self.assertLess(commands.index('.reload /s /f combase.dll'), commands.index('bu10 '))
        self.assertLess(commands.index('bu10 '), commands.index('bl 10'))
        self.assertEqual(commands.count('.reload /s /f combase.dll'), 1)
        self.assertIn('HARNESS77_OBSERVER_BOUND_BEGIN:' + self.id, commands)

    def test_enabled_resolved_entry_is_accepted(self):
        self.assertEqual(observer_binding(self.binding(), self.id),
                         {'address': '75fb7b30', 'symbol': 'combase!CoRegisterClassObject'})

    def test_unresolved_disabled_wrong_symbol_offset_or_duplicate_rows_are_refused(self):
        rows = ['10 eu 0001 (0001) (combase!CoRegisterClassObject)',
                '10 d 75fb7b30 0001 (0001) combase!CoRegisterClassObject',
                '10 e 00000000 0001 (0001) combase!CoRegisterClassObject',
                '10 e 75fb7b30 0001 (0001) combase!OtherEntry',
                '10 e 75fb7b34 0001 (0001) combase!CoRegisterClassObject+0x4',
                '10 e 75fb7b30 0001 (0001) combase!CoRegisterClassObject\n'
                '10 e 75fb7b30 0001 (0001) combase!CoRegisterClassObject']
        for row in rows:
            with self.subTest(row=row), self.assertRaises(ValueError):
                observer_binding(self.binding(row), self.id)

    def test_command_echoes_foreign_and_partial_sections_are_not_binding_evidence(self):
        text = self.binding()
        self.assertIsNone(observer_binding(text, str(uuid4())))
        self.assertIsNone(observer_binding(text[:text.index('HARNESS77_OBSERVER_BOUND_END')], self.id))
        self.assertIsNone(observer_binding(text.replace('HARNESS77_OBSERVER_BOUND_BEGIN', '0:000> .echo HARNESS77_OBSERVER_BOUND_BEGIN'), self.id))
        with self.assertRaises(ValueError):
            observer_binding(text + text, self.id)

    def test_command_ready_marker_is_exact_and_unique(self):
        marker = command_marker(self.id)
        self.assertTrue(commands_processed(marker + '\n', self.id))
        self.assertFalse(commands_processed('0:000> .echo ' + marker + '\n', self.id))
        self.assertFalse(commands_processed(marker, str(uuid4())))
        with self.assertRaises(ValueError):
            commands_processed(marker + '\n' + marker, self.id)

    def test_trace_preserves_phase_cancel_and_unique_observation_times(self):
        trace = StartupTrace(self.out, self.id, clock=iter([1, 1.1, 1.2]).__next__)
        trace.note('debugger_created', waiting_for='server_ownership', pid=42)
        trace.note('debugger_created', waiting_for='wrong', pid=99)
        trace.note('server_owned', waiting_for='debugger_commands', pid=43)
        trace.finish('cancelled by caller', True)
        saved = json.loads((self.out / 'startup.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['status'], 'cancelled')
        self.assertEqual(saved['waiting_for'], 'debugger_commands')
        self.assertEqual([e['stage'] for e in saved['events']], ['debugger_created', 'server_owned'])
        self.assertEqual([e['observed_s'] for e in saved['events']], [0.1, 0.2])
        self.assertFalse((self.out / 'startup.json.tmp').exists())


if __name__ == '__main__':
    unittest.main()
