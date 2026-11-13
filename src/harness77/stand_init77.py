"""Create a qualified native stand profile; never launch or register anything."""
import argparse
import ast
import json
import os
from pathlib import Path
import sys
import tomllib

from .artifacts import _destination, _publish
from .basecopy77 import lock_path
from .doctor77 import pe_machine
from .ert_module import ErtError
from . import native_runtime77 as runtime
from .report77 import sha256_file


class StandInitError(ValueError):
    pass


def _inspector():
    if os.name != 'nt':
        raise StandInitError('Создание нативного стенда требует Windows')
    from .doctor_windows77 import WindowsInspector
    return WindowsInspector()


def _literal(path, name):
    """Read a literal policy constant without executing/importing native modules."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    assignments = [node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    if len(assignments) != 1:
        raise StandInitError('Неоднозначная политика runtime: ' + name)
    return ast.literal_eval(assignments[0])


def _qualification():
    payload = runtime.HERE / '_native/platform77'
    pinned = _literal(payload / 'shutdown77.py', 'PINNED')
    identity = _literal(payload / 'concurrent77.py', 'IDENTITY_SHA')
    expected = {'exe', 'helper', '1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll'}
    if not isinstance(pinned, dict) or set(pinned) != expected or not isinstance(identity, str):
        raise StandInitError('Неподдерживаемая политика квалификации runtime')
    return {**pinned, 'identity': identity}


def _text(value, role, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise StandInitError(role + ': нужна строка без управляющих символов')
    return value


def _render(stand):
    lines = ['schema_version = 1', '']
    for name, fields in [('stand', {k: v for k, v in stand.items() if not isinstance(v, dict)}),
                         *[('stand.' + key, stand[key]) for key in ('paths', 'base', 'pinned', 'tool_hashes')]]:
        lines += ['[' + name + ']']
        lines += [json.dumps(k, ensure_ascii=False) + ' = ' + json.dumps(v, ensure_ascii=False) for k, v in fields.items()]
        lines.append('')
    text = '\n'.join(lines)
    tomllib.loads(text)
    return text.encode('utf-8')


def initialize(*, output, name, adapter, exe, cdb, helper, identity, base, copy_path, user, copy_exclude=(), windows=None):
    destination = _destination(output)  # refuses existing files, dirs and dangling links
    observer = _inspector() if windows is None else windows
    info = runtime.inspect_runtime(adapter)
    expected = _qualification()
    base = Path(base).resolve(strict=True)
    if not base.is_dir():
        raise StandInitError('base: нужен существующий каталог')
    if os.path.lexists(copy_path):
        raise StandInitError('copy_path: копия или ссылка уже существуют')
    target = Path(copy_path).resolve()
    if not target.parent.is_dir():
        raise StandInitError('copy_path: родительский каталог должен существовать')
    if base.is_relative_to(target) or target.is_relative_to(base):
        raise StandInitError('base и copy_path не должны пересекаться')
    if destination.is_relative_to(base) or destination.is_relative_to(target):
        raise StandInitError('Профиль нельзя создавать внутри базы или пути копии')
    excludes = []
    for item in copy_exclude:
        _text(item, 'copy-exclude')
        if item in ('.', '..') or item != item.rstrip(' .') or any(c in item for c in '/\\:*?"<>|'):
            raise StandInitError('copy-exclude: нужно имя подкаталога верхнего уровня')
        if (base / item).exists() and not (base / item).is_dir():
            raise StandInitError('copy-exclude: нельзя исключать файл базы')
        if item not in excludes:
            excludes.append(item)

    def copy_idle():
        if os.path.lexists(target) or os.path.lexists(lock_path(target)):
            raise StandInitError('copy_path: копия или её замок уже существуют')
        if not observer.registered(target):
            raise StandInitError('copy_path: путь не зарегистрирован в списке баз 1С')

    copy_idle()
    paths = {role: Path(path).resolve(strict=True) for role, path in
             (('exe', exe), ('cdb', cdb), ('helper', helper), ('identity', identity))}
    inputs = {**paths, **{key: base / key for key in ('1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')}}
    hashes = {}
    for role, path in inputs.items():
        if not path.is_file():
            raise StandInitError(role + ': нужен обычный файл')
        if role not in ('1Cv7.MD', '1Cv7.DD') and pe_machine(path) != 0x14c:
            raise StandInitError(role + ': требуется PE x86')
        hashes[role] = sha256_file(path)
        if role != 'cdb' and hashes[role] != expected[role]:
            raise StandInitError(role + ': SHA-256 не соответствует квалифицированному runtime')
    for key in ('1SUSERS.DBF', '1SJOURN.DBF'):
        with (base / key).open('rb') as stream:
            stream.read(32)
    settings = {'name': _text(name, 'name'), 'backend': 'native', 'runtime': adapter,
                'platform_version': info['platform_version'], 'screenshots': False,
                'credential_source': 'empty password authorized by owner; not stored',
                'paths': {key: value.as_posix() for key, value in paths.items()},
                'base': {'path': base.as_posix(), 'user': _text(user, 'user', empty=True),
                         'copy_path': target.as_posix(), 'copy_exclude': excludes},
                'pinned': {key: hashes[key] for key in ('exe', '1Cv7.MD', '1Cv7.DD', '1CPP.dll', 'FormEx.dll')},
                'tool_hashes': {key: hashes[key] for key in ('cdb', 'helper', 'identity')}}
    payload = _render(settings)

    def verify(disk):
        tomllib.loads(disk.decode('utf-8'))
        if runtime.inspect_runtime(adapter) != info:
            raise StandInitError('Runtime изменился во время подготовки профиля')
        copy_idle()
        for role, path in inputs.items():
            if sha256_file(path) != hashes[role]:
                raise StandInitError(role + ': файл изменился во время подготовки профиля')

    # Same staged, read-back, hard-link publication as the artifact commands.
    profile = _publish(destination, payload, verify, [])
    return {'status': 'created', 'exit_code': 0, 'platform_checked': False, 'launch_performed': False,
            'profile': profile, 'runtime': info, 'reason': None}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='harness77 stand-init', allow_abbrev=False, description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--runtime', dest='adapter', choices=runtime.ADAPTERS, required=True)
    for key in ('exe', 'cdb', 'helper', 'identity', 'base', 'copy-path'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--user', required=True, help='Пользователь 1С с ранее разрешённым пустым паролем')
    parser.add_argument('--copy-exclude', action='append', default=[], help='Имя исключаемого подкаталога; можно повторять')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    args = vars(parser.parse_args(argv))
    format_ = args.pop('format')
    try:
        report = initialize(**args)
    except (OSError, ValueError, ErtError, SyntaxError) as error:
        report = {'status': 'blocked', 'exit_code': 2, 'platform_checked': False, 'launch_performed': False,
                  'reason': f'{type(error).__name__}: {error}'}
    if format_ == 'json':
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif report['status'] == 'created':
        print('stand-init: создан ' + report['profile']['path'])
        print('runtime ' + report['runtime']['runtime_version'] + '; запуск 1С не выполнялся')
    else:
        print('stand-init: blocked: ' + report['reason'], file=sys.stderr)
    return report['exit_code']
