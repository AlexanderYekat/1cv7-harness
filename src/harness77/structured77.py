"""Bounded, exact JSON expectations on this run's operation value (096).

Application semantics and labels live in the project. This module only captures
the returned text and compares JSON trees; it never reads arbitrary input paths.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import json

from .report77 import file_evidence

MAX_BYTES = 1 << 20
MAX_DEPTH = 64
MAX_NODES = 20000
MAX_DIFFERENCES = 100


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate JSON key: " + key[:120])
        value[key] = item
    return value


def _constant(value):
    raise ValueError("non-finite JSON number: " + value)


def pointer(path, key):
    return path + '/' + str(key).replace('~', '~0').replace('/', '~1')


def _walk(value, path='', depth=0):
    if depth > MAX_DEPTH:
        raise ValueError("JSON nesting exceeds " + str(MAX_DEPTH))
    yield path
    children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, item in children:
        yield from _walk(item, pointer(path, key), depth + 1)


def parse(text):
    if not isinstance(text, str):
        raise ValueError("JSON result must be text")
    if len(text) > MAX_BYTES or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError("JSON exceeds 1 MiB")
    try:
        value = json.loads(text, parse_float=Decimal, object_pairs_hook=_pairs, parse_constant=_constant)
        for count, _ in enumerate(_walk(value), 1):
            if count > MAX_NODES:
                raise ValueError("JSON exceeds " + str(MAX_NODES) + " nodes")
    except (RecursionError, UnicodeError, InvalidOperation) as error:
        raise ValueError("invalid or excessively nested JSON") from error
    # Escaped lone surrogates are legal to json.loads, but cannot form UTF-8 evidence.
    json.dumps(value, ensure_ascii=False, default=str).encode('utf-8')
    return value


def validate(expected, labels):
    """Validate project declarations before starting a platform session."""
    value = parse(expected)
    if not isinstance(labels, dict) or len(labels) > MAX_NODES:
        raise ValueError("json_labels must be a table of JSON Pointers and labels")
    paths = set(_walk(value))
    for path, label in labels.items():
        if path not in paths or not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise ValueError("json_labels requires an existing JSON Pointer and a non-empty label (max 160 characters)")
        if any(ord(c) < 32 for c in label):
            raise ValueError("json_labels contains a control character")


def _kind(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, Decimal)):
        return 'number'
    return {str: 'string', list: 'array', dict: 'object'}[type(value)]


def _public(value):
    # Decimal never rounds through binary float. Fractional JSON numbers are
    # decimal strings in diagnostics, disambiguated by expected/actual_type.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def compare(expected, actual, labels=None):
    labels = labels or {}
    differences, count = [], 0
    absent = object()

    def mismatch(path, code, a, b):
        nonlocal count
        count += 1
        if len(differences) == MAX_DIFFERENCES:
            return
        row = {'path': path, 'label': labels.get(path, path or '/'), 'code': code,
               'expected_present': a is not absent, 'actual_present': b is not absent}
        display = {}
        for name, value in (('expected', a), ('actual', b)):
            if value is absent:
                display[name] = 'отсутствует'
                continue
            row[name + '_type'] = _kind(value)
            public = _public(value)
            text = json.dumps(public, ensure_ascii=False)
            row[name] = public if len(text) <= 2000 else text[:2000]
            if len(text) > 2000:
                row[name + '_truncated'] = True
            display[name] = text[:200]
        row['message'] = f"{row['label']}: ожидалось {display['expected']}, получено {display['actual']}"
        differences.append(row)

    def visit(a, b, path=''):
        if _kind(a) != _kind(b):
            mismatch(path, 'type_mismatch', a, b)
        elif isinstance(a, dict):
            for key in a:
                if key not in b:
                    mismatch(pointer(path, key), 'missing_field', a[key], absent)
                else:
                    visit(a[key], b[key], pointer(path, key))
            for key in b:
                if key not in a:
                    mismatch(pointer(path, key), 'unexpected_field', absent, b[key])
        elif isinstance(a, list):
            for index in range(max(len(a), len(b))):
                if index >= len(a):
                    mismatch(pointer(path, index), 'unexpected_item', absent, b[index])
                elif index >= len(b):
                    mismatch(pointer(path, index), 'missing_item', a[index], absent)
                else:
                    visit(a[index], b[index], pointer(path, index))
        elif a != b:
            mismatch(path, 'value_mismatch', a, b)

    visit(expected, actual)
    return {'status': 'failed' if count else 'passed', 'difference_count': count,
            'differences': differences, 'differences_truncated': count > len(differences)}


def judge(test, value, run_dir, run_id, index):
    """Capture only the linked operation's text; unreadable results block judging."""
    result = {'status': 'blocked', 'difference_count': 0, 'differences': [], 'differences_truncated': False}

    def error(code, message):
        result['diagnostics'] = [{'code': code, 'message': message}]
        return result

    if value is None:
        return error('json_result_missing', 'Операция не вернула JSON-результат')
    if not isinstance(value, str):
        return error('json_result_invalid', 'JSON-результат должен быть текстом')
    try:
        if len(value) > MAX_BYTES:
            return error('json_result_limit', 'JSON-результат превышает 1 MiB')
        data = value.encode('utf-8')
        if len(data) > MAX_BYTES:
            return error('json_result_limit', 'JSON-результат превышает 1 MiB')
    except UnicodeError:
        return error('json_result_invalid', 'JSON-результат содержит некорректный Unicode')
    try:
        folder = run_dir / 'structured'
        folder.mkdir(exist_ok=True)
        path = folder / f'test-{index:04d}.actual.json'
        with path.open('xb') as stream:
            stream.write(data)
        result['result'] = dict(file_evidence(path, root=run_dir, complete=True,
                                             expected_sha256=hashlib.sha256(data).hexdigest()),
                                run_id=run_id, operation=test['command'])
        if not (result['result'].get('exists') and result['result'].get('complete')
                and result['result'].get('sha256_matches') and result['result'].get('size_bytes') == len(data)):
            return error('json_result_write_error', 'Записанный JSON-результат не подтверждён обратным чтением')
    except OSError as exc:
        return error('json_result_write_error', f'Не сохранён JSON-результат: {type(exc).__name__}')
    if not value.strip():
        return error('json_result_missing', 'Операция вернула пустой JSON-результат')
    try:
        actual = parse(value)
    except (ValueError, UnicodeError) as exc:
        return error('json_result_invalid', 'Некорректный JSON-результат: ' + str(exc)[:300])
    result.update(compare(parse(test['expect_json']), actual, test.get('json_labels')))
    result['diagnostics'] = result['differences']
    return result
