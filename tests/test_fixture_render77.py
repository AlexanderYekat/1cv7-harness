"""The installed-style fixture generator verifies input and publishes both files together."""
from contextlib import redirect_stdout
import hashlib
from importlib.resources import files
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness77 import cli, fixture_render77 as generator


class FixtureRenderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='fixture112-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()

    def sample(self, kind):
        return files('harness77').joinpath('fixture_recipes', kind + '.toml').read_bytes()

    def invoke(self, kind, output, recipe=None):
        args = ['fixture-render', '--kind', kind, '--output', str(output), '--format', 'json']
        if recipe is not None:
            args.extend(['--recipe', str(recipe)])
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            status = cli.main(args)
        return status, json.loads(buffer.getvalue())

    def test_both_bundled_recipes_publish_validated_utf8_bodies(self):
        cases = [('services', 'ОказаниеУслуг', 'ТипУслуги = 1;', 'Док77.Услуга'),
                 ('invoice', 'СчетФактура', 'НазначитьТип("Товар"', 'Док77.Товар')]
        for kind, document, setup_fragment, reader_fragment in cases:
            with self.subTest(kind=kind):
                output = self.root / kind
                status, report = self.invoke(kind, output)
                self.assertEqual((status, report['status']), (0, 'created'))
                self.assertFalse(report['launch_performed'])
                self.assertFalse(report['platform_checked'])
                self.assertEqual(report['recipe']['source'], 'bundled')
                self.assertEqual(report['recipe']['sha256'], hashlib.sha256(self.sample(kind)).hexdigest())
                self.assertEqual({p.name for p in output.iterdir()}, {'fixture.1s', 'reader.1s'})
                for name, fragment in [('fixture.1s', setup_fragment), ('reader.1s', reader_fragment)]:
                    raw = (output / name).read_bytes()
                    text = raw.decode('utf-8')
                    text.encode('cp1251')
                    self.assertIn(f'СоздатьОбъект("Документ.{document}")', text)
                    self.assertIn(fragment, text)
                    self.assertEqual(report['files'][name]['sha256'], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(report['files'][name]['size_bytes'], len(raw))

    def test_custom_toml_changes_the_fixture_and_reader_without_changing_the_input(self):
        output = self.root / 'generated'
        recipe = self.root / 'проект рецепта.toml'
        text = self.sample('invoice').decode('utf-8').replace('Harness77 товар 100', 'Мой \\"товар\\"')
        recipe.write_bytes(text.encode('utf-8-sig'))
        raw = recipe.read_bytes()
        status, report = self.invoke('invoice', output, recipe)
        self.assertEqual(status, 0)
        self.assertEqual(report['recipe']['source'], 'file')
        self.assertEqual(report['recipe']['path'], str(recipe))
        self.assertEqual(recipe.read_bytes(), raw)
        for name in ('fixture.1s', 'reader.1s'):
            self.assertIn('Мой ""товар""', (output / name).read_text('utf-8'))

    def test_invalid_kind_recipe_type_and_reader_field_do_not_create_output(self):
        valid = self.sample('invoice').decode('utf-8')
        cases = [('services', valid, 'fixture'),
                 ('invoice', valid.replace('quantity = 1', 'quantity = true'), 'fixture.rows[0]'),
                 ('invoice', valid.replace('price = "Цена"', 'price = "Цена()"'), 'reader.rows.price'),
                 ('invoice', valid.replace('Harness77 товар 100', 'Товар 🙂'), 'UnicodeEncodeError')]
        for index, (kind, text, reason) in enumerate(cases):
            output, recipe = self.root / f'result{index}', self.root / f'input{index}.toml'
            with self.subTest(reason=reason):
                recipe.write_bytes(text.encode('utf-8'))
                status, report = self.invoke(kind, output, recipe)
                self.assertEqual((status, report['status']), (2, 'blocked'))
                self.assertIn(reason, report['reason'])
                self.assertFalse(output.exists())
                self.assertFalse(list(self.root.glob('.harness77-fixture-*')))

    def test_write_failure_removes_the_private_stage_and_leaves_no_partial_result(self):
        write = generator._write

        def fail_second(path, payload):
            if path.name == 'reader.1s':
                raise OSError('injected reader write failure')
            write(path, payload)

        output = self.root / 'output'
        with patch.object(generator, '_write', side_effect=fail_second):
            status, report = self.invoke('invoice', output)
        self.assertEqual(status, 2)
        self.assertIn('injected reader write failure', report['reason'])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_racing_existing_empty_output_survives(self):
        output = self.root / 'output'
        rename = generator._rename_new

        def competitor(stage, destination):
            destination.mkdir()
            return rename(stage, destination)

        with patch.object(generator, '_rename_new', side_effect=competitor):
            status, report = self.invoke('invoice', output)
        self.assertEqual((status, report['status']), (2, 'blocked'))
        self.assertEqual(list(self.root.iterdir()), [output])
        self.assertEqual(list(output.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
