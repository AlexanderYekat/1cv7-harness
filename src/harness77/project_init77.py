"""Create a headless or application forms project without replacing existing paths."""
import argparse
import ctypes
import errno
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib

from .artifacts import _container, _destination, _input
from .config77 import load_project
from .deadlines77 import Deadlines
from .ert_module import ErtError, decompress_module
from .report77 import sha256_bytes

PREFIX = '.harness77-project-'
NAMES = ('project.toml', 'module.1s', 'template.ert', 'scenario.json')


def _toml(value):
    if isinstance(value, dict):
        return '{ ' + ', '.join(json.dumps(k, ensure_ascii=False) + ' = ' + _toml(v)
                                 for k, v in value.items()) + ' }'
    if isinstance(value, list):
        return '[' + ', '.join(map(_toml, value)) + ']'
    if value is None:
        raise ValueError('scenario: null не поддерживается профилем TOML')
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _scenario(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('scenario: повторный ключ ' + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError('scenario: недопустимое число ' + value)

    data = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(data, dict) or set(data) - {'parameters', 'tests'}:
        raise ValueError('scenario: допустимы только parameters и tests')
    tests = data.get('tests')
    if not isinstance(data.get('parameters'), dict) or not isinstance(tests, list) or not tests:
        raise ValueError('scenario: нужны parameters и непустой список tests')
    allowed = {'name', 'command', 'expect', 'description', 'expect_value', 'expect_json', 'json_labels'}
    names = set()
    for test in tests:
        if not isinstance(test, dict) or set(test) - allowed:
            raise ValueError('scenario: неизвестные поля теста')
        for key in ('name', 'command', 'expect'):
            if not isinstance(test.get(key), str) or not test[key].strip():
                raise ValueError('scenario: тест требует непустую строку ' + key)
        if test['name'] in names:
            raise ValueError('scenario: повторное имя теста ' + test['name'])
        names.add(test['name'])
        for key in ('description', 'expect_value', 'expect_json'):
            if key in test and not isinstance(test[key], str):
                raise ValueError('scenario: ' + key + ' должен быть строкой')
    return data


def _rename_new(source, destination):
    """No overwrite race, including when the competing destination is empty."""
    if os.name == 'nt':
        os.rename(source, destination)  # Windows refuses every existing destination.
    elif sys.platform.startswith('linux'):
        library = ctypes.CDLL(None, use_errno=True)
        function = getattr(library, 'renameat2', None)
        if function is None:
            raise OSError(errno.ENOSYS, 'renameat2(RENAME_NOREPLACE) is unavailable')
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        function.restype = ctypes.c_int
        if function(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(destination))
    else:
        raise OSError(errno.ENOTSUP, 'atomic directory publication without replacement is unavailable')


def _write(path, payload):
    with path.open('xb') as stream:
        if stream.write(payload) != len(payload):
            raise OSError('Неполная запись файла проекта')
        stream.flush()
        os.fsync(stream.fileno())


def _cleanup(stage, parent):
    # Delete only known files in our private sibling, never recursively delete
    # a computed/user directory or a competing destination.
    if stage.is_symlink() or stage.resolve().parent != parent.resolve() or not stage.name.startswith(PREFIX):
        raise OSError('Не подтверждён временный каталог проекта: ' + str(stage))
    for name in NAMES:
        (stage / name).unlink(missing_ok=True)
    config = stage / 'configuration'
    if config.exists():
        config.rmdir()
    stage.rmdir()  # Any unexpected file is preserved and makes cleanup fail.


def initialize(*, directory, project_id, template, open_timeout_s, calculation_timeout_s,
               cancel_timeout_s, shutdown_timeout_s, total_timeout_s, runtime='headless',
               source=None, scenario=None):
    destination = _destination(directory)
    if runtime not in ('headless', 'forms'):
        raise ValueError('runtime: допустимы headless и forms')
    if runtime == 'forms' and (source is None or scenario is None):
        raise ValueError('forms требует --source и --scenario')
    if runtime == 'headless' and (source is not None or scenario is not None):
        raise ValueError('--source и --scenario допустимы только с --runtime forms')
    if not isinstance(project_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', project_id) or project_id.endswith('.'):
        raise ValueError('id: нужны 1–64 ASCII-буквы/цифры, точка, дефис или подчёркивание; начало — буква/цифра')
    reserved = {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10))}
    if project_id.split('.')[0].upper() in reserved:
        raise ValueError('id: зарезервированное имя файла Windows')
    deadlines = Deadlines.create(open_s=open_timeout_s, calculation_s=calculation_timeout_s,
                                cancel_s=cancel_timeout_s, shutdown_s=shutdown_timeout_s, total_s=total_timeout_s)
    limits = {name + '_timeout_s': deadlines.limit(name) for name in ('open', 'calculation', 'cancel', 'shutdown')}
    limits['total_timeout_s'] = deadlines.total_s
    original, raw = _input(template)
    inputs = [(original, raw)]
    compound, module, _ = _container(raw)
    decompress_module(compound.read_stream(module)).decode('cp1251')
    platform = {'tests': [{'name': 'control-42', 'command': 'execute', 'expect': 'passed', 'expect_value': '42'}]}
    if runtime == 'forms':
        source_path, source_bytes = _input(source)
        scenario_path, scenario_bytes = _input(scenario)
        inputs += [(source_path, source_bytes), (scenario_path, scenario_bytes)]
        platform = _scenario(scenario_bytes)
    else:
        source_bytes = files('harness77').joinpath('project_headless77.1s').read_bytes()
    source_text = source_bytes.decode('utf-8')
    source_text.encode('cp1251', errors='strict')
    if not source_text.strip():
        raise ValueError('source: пустой модуль')
    text = ('schema_version = ' + ('2' if runtime == 'forms' else '1') + '\n\n[project]\nid = ' + json.dumps(project_id) + '\n\n'
            '[build]\ntemplate = "template.ert"\nsource = "module.1s"\nencoding = "utf-8"\n\n'
            '[configuration]\nmodules = "configuration"\n\n'
            '[platform]\n' + ''.join(key + ' = ' + _toml(value) + '\n' for key, value in platform.items()) + '\n'
            '[deadlines]\n' + ''.join(key + ' = ' + json.dumps(value, allow_nan=False) + '\n' for key, value in limits.items()))
    tomllib.loads(text)
    payloads = {'project.toml': text.encode('utf-8'), 'module.1s': source_bytes, 'template.ert': raw}
    if runtime == 'forms':
        payloads['scenario.json'] = scenario_bytes
    stage = Path(tempfile.mkdtemp(prefix=PREFIX, dir=destination.parent))
    published = False
    try:
        (stage / 'configuration').mkdir()
        for name, payload in payloads.items():
            _write(stage / name, payload)
        for name, payload in payloads.items():
            if (stage / name).read_bytes() != payload:
                raise ErtError('Перечитанные байты проекта отличаются: ' + name)
        project = load_project(stage / 'project.toml')
        if project.template != stage / 'template.ert' or project.source != stage / 'module.1s' or project.configuration != stage / 'configuration':
            raise ErtError('Неверные относительные пути проекта')
        for path, data in inputs:
            if path.read_bytes() != data:
                raise ErtError('Шаблон изменился или другой вход изменился во время создания проекта: ' + str(path))
        _rename_new(stage, destination)
        published = True
    finally:
        if not published:
            _cleanup(stage, destination.parent)
    return {'status': 'created', 'exit_code': 0, 'platform_checked': False, 'launch_performed': False,
            'directory': str(destination), 'project': str(destination / 'project.toml'), 'runtime': runtime,
            'inputs': [{'path': str(path), 'sha256': sha256_bytes(data), 'size_bytes': len(data)} for path, data in inputs],
            'files': {name: {'sha256': sha256_bytes(data), 'size_bytes': len(data)} for name, data in payloads.items()},
            'directories': ['configuration'], 'template': {'path': str(original), 'sha256': sha256_bytes(raw)},
            'reason': None}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='harness77 project-init', allow_abbrev=False, description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--id', dest='project_id', required=True)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--runtime', choices=('headless', 'forms'), default='headless')
    parser.add_argument('--source', type=Path, help='UTF-8 модуль прикладного forms-проекта')
    parser.add_argument('--scenario', type=Path, help='UTF-8 JSON с parameters и tests для forms')
    for phase in ('open', 'calculation', 'cancel', 'shutdown', 'total'):
        parser.add_argument('--' + phase + '-timeout-s', type=float, required=True)
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    args = vars(parser.parse_args(argv))
    format_ = args.pop('format')
    try:
        report = initialize(**args)
    except (OSError, ValueError, ErtError) as error:
        report = {'status': 'blocked', 'exit_code': 2, 'platform_checked': False, 'launch_performed': False,
                  'reason': f'{type(error).__name__}: {error}'}
    if format_ == 'json':
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif report['status'] == 'created':
        print('project-init: создан ' + report['project'])
        print('Проверка: ' + ('прикладной forms-сценарий' if report['runtime'] == 'forms' else 'execute ожидает 42')
              + '; запуск 1С не выполнялся')
    else:
        print('project-init: blocked: ' + report['reason'], file=sys.stderr)
    return report['exit_code']
