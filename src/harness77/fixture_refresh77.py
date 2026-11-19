"""Update the generated pair in a recipe project, refusing local edits."""
import argparse
import json
from pathlib import Path
import sys
import tomllib

from .artifacts import _input, _unchanged
from .config77 import FILE_FIXTURE_SCHEMA_VERSION, FIXTURE_RECIPE_FILE, FIXTURE_REFRESH_LOCK, JSON_FILE_SCHEMA_VERSION
from .ert_module import ErtError
from .fixture_render77 import DOCUMENTS, read_recipe, render
from .project_init77 import _write
from .report77 import sha256_bytes

FILES = ('fixture.1s', 'reader.1s', FIXTURE_RECIPE_FILE)


class RefreshConflict(ValueError):
    def __init__(self, names):
        self.files = names
        super().__init__('Файлы отличаются от генерации по сохранённому рецепту: ' + ', '.join(names))


def _kind(profile):
    data = tomllib.loads(profile.decode('utf-8-sig'))
    platform = data.get('platform')
    parameters = platform.get('parameters') if isinstance(platform, dict) else None
    if (data.get('schema_version') not in (FILE_FIXTURE_SCHEMA_VERSION, JSON_FILE_SCHEMA_VERSION)
            or not isinstance(parameters, dict)
            or parameters.get('fixture_mode') != 'existing'
            or parameters.get('fixture_setup_file') != 'fixture.1s'
            or parameters.get('fixture_verify_file') != 'reader.1s'
            or 'fixture_setup' in parameters or 'fixture_verify' in parameters):
        raise ValueError('Нужен профиль проекта, подготовленного project-init --fixture-kind')
    form = parameters.get('form_object')
    if isinstance(form, str):
        for kind, document in DOCUMENTS.items():
            if form.casefold() == ('Документ.' + document).casefold():
                return kind
    raise ValueError('form_object не соответствует рецепту services или invoice')


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Нужен обычный файл проекта: ' + path.name)
    return path.read_bytes()


def refresh(*, project, recipe):
    profile, profile_bytes = _input(project)
    kind = _kind(profile_bytes)
    parent = profile.parent
    recipe_bytes, recipe_path, source = read_recipe(kind, recipe)
    if recipe_path in {parent / name for name in FILES} | {profile}:
        raise ValueError('--recipe: нужен отдельный файл, fixture-recipe.toml хранит предыдущий рецепт')
    new = {**render(kind, recipe_bytes), FIXTURE_RECIPE_FILE: recipe_bytes}
    lock = parent / FIXTURE_REFRESH_LOCK
    try:
        lock.mkdir()
    except FileExistsError:
        raise OSError(f'Обновление fixture не завершено: {lock}') from None
    keep_lock = False
    try:
        old = {name: _read(parent / name) for name in FILES}
        expected = render(kind, old[FIXTURE_RECIPE_FILE])
        modified = [name for name, payload in expected.items() if old[name] != payload]
        if modified:
            raise RefreshConflict(modified)
        changed = [name for name in FILES if old[name] != new[name]]
        for name in changed:
            for prefix, content in (('new-', new[name]), ('old-', old[name])):
                stage = lock / (prefix + name)
                _write(stage, content)
                if stage.read_bytes() != content:
                    raise OSError(f'Данные временного файла отличаются: {name}')
        _unchanged([(profile, profile_bytes), (recipe_path, recipe_bytes)])
        modified = [name for name in FILES if _read(parent / name) != old[name]]
        if modified:
            raise RefreshConflict(modified)
        attempted = []
        try:
            for name in changed:
                target = parent / name
                if _read(target) != old[name]:
                    raise RefreshConflict([name])
                attempted.append(name)
                (lock / ('new-' + name)).replace(target)
        except BaseException:
            # Ctrl+C can arrive after a replace succeeds but before Python resumes.
            keep_lock = True
            failures = []
            for name in reversed(attempted):
                target = parent / name
                try:
                    current = _read(target)
                    if current == old[name]:
                        continue
                    if current != new[name]:
                        raise RefreshConflict([name])
                    (lock / ('old-' + name)).replace(target)
                except (OSError, ValueError) as error:
                    failures.append(f'{name}: {error}')
            if failures:
                raise OSError(f'Не удалось откатить обновление. Резервные файлы: {lock}. ' + ', '.join(failures))
            keep_lock = False
            raise
    finally:
        if not keep_lock:
            for name in FILES:
                for prefix in ('old-', 'new-'):
                    (lock / (prefix + name)).unlink(missing_ok=True)
            lock.rmdir()
    return {'status': 'updated' if changed else 'unchanged', 'exit_code': 0, 'project': str(profile),
            'kind': kind, 'platform_checked': False, 'launch_performed': False, 'recipe': source,
            'changed': changed, 'files': {name: {'sha256': sha256_bytes(data), 'size_bytes': len(data)}
                                          for name, data in new.items()}, 'reason': None}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='harness77 fixture-refresh', allow_abbrev=False, description=__doc__)
    parser.add_argument('--project', type=Path, required=True, help='профиль project.toml')
    parser.add_argument('--recipe', type=Path, required=True, help='новый рецепт в отдельном файле TOML')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    args = parser.parse_args(argv)
    try:
        report = refresh(project=args.project, recipe=args.recipe)
    except (OSError, ValueError, ErtError) as error:
        report = {'status': 'blocked', 'exit_code': 2, 'platform_checked': False, 'launch_performed': False,
                  'reason': f'{type(error).__name__}: {error}'}
        if isinstance(error, RefreshConflict):
            report['conflicts'] = error.files
    if args.format == 'json':
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif report['status'] == 'blocked':
        print('fixture-refresh: blocked: ' + report['reason'], file=sys.stderr)
    elif report['changed']:
        print('fixture-refresh: обновлены ' + ', '.join(report['changed']))
    else:
        print('fixture-refresh: файлы совпадают с рецептом')
    return report['exit_code']
