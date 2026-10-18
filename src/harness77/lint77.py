#!/usr/bin/env python3
"""Conservative, dependency-free static checks for 1C 7.7 (not its compiler)."""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import asdict, dataclass, field
import json
from importlib.resources import files
import os
from pathlib import Path
import re
import struct
import sys
import zlib

from .catalog77 import load_packaged
from .ert_module import (DIALOG_STREAM, CompoundFile, ErtError, decode_dialog, decode_source_bytes,
                         dialog_controls)

VERSION = '0.2.0'
LIMITATIONS = [
    'Частичный разбор языка; отсутствие диагностик не означает успешную компиляцию 1С.',
    'Имена встроенных функций и методов — из каталога платформы 7.70.027; неизвестные вызовы '
    'по умолчанию — предупреждения.',
    'Типы, методы конфигурации, COM и внешних компонент, динамически исполняемый код не проверяются.',
    'Объявление переменных (L7711) проверяется только в модуле с известным диалогом: ERT или --dialog.',
    'Доступность известных встроенных функций в конкретном контексте модуля не проверяется.',
    'Проводки, запросы и корректность бухгалтерского учета не проверяются.',
]
# Confirmed on 7.70.027 (docs/tasks/005-kudir-rules-acceptance.md): the 1C 7.7 module
# compiler accepts much longer lines; the Configurator refused a 590-character one.
LINE_LIMIT = 500
# A token after these starts a statement, so "Имя =" there is an assignment.
STATEMENT_START = {'тогда', 'then', 'иначе', 'else', 'цикл', 'do', 'попытка', 'try',
                   'исключение', 'except'}
CYRILLIC = re.compile('[А-Яа-яЁё]')
KEYWORDS = set('если if тогда then иначе else иначеесли elsif elseif конецесли endif '
               'пока while для for по to цикл do конеццикла enddo '
               'попытка try исключение except конецпопытки endtry '
               'процедура procedure функция function конецпроцедуры endprocedure '
               'конецфункции endfunction далее forward экспорт export '
               'знач val перем var и and или or не not возврат return '
               'прервать break продолжить continue перейти goto'.split())
DECL = {'процедура': 'procedure', 'procedure': 'procedure',
        'функция': 'function', 'function': 'function'}
CLOSE = {'конецпроцедуры': 'procedure', 'endprocedure': 'procedure',
         'конецфункции': 'function', 'endfunction': 'function',
         'конецесли': 'if', 'endif': 'if', 'конеццикла': 'loop',
         'enddo': 'loop', 'конецпопытки': 'try', 'endtry': 'try'}
KNOWN8 = {
    'обработкапрерыванияпользователя': 'ОбработкаПрерыванияПользователя',
    'userinterruptprocessing': 'UserInterruptProcessing',
    'значениезаполнено': 'ЗначениеЗаполнено', 'valueisfilled': 'ValueIsFilled',
    'типзнч': 'ТипЗнч', 'typeof': 'TypeOf',
    'получитьимявременногофайла': 'ПолучитьИмяВременногоФайла',
    'gettempfilename': 'GetTempFileName',
    'стрсоединить': 'СтрСоединить', 'strconcat': 'StrConcat',
    'стрразделить': 'СтрРазделить', 'strsplit': 'StrSplit',
    'числопрописью': 'ЧислоПрописью', 'numberinwords': 'NumberInWords',
    'год': 'Год', 'year': 'Year', 'месяц': 'Месяц', 'month': 'Month',
    'день': 'День', 'day': 'Day',
}


@dataclass
class Diagnostic:
    path: str
    module: str
    line: int
    column: int
    rule: str
    severity: str
    message: str


@dataclass
class Token:
    kind: str
    text: str
    line: int
    column: int

    @property
    def key(self):
        return self.text.casefold()


@dataclass
class Symbol:
    name: str
    token: Token
    kind: str
    # True means the parameter has a default value.
    optional: list[bool]
    exported: bool = False
    forward: bool = False
    params: list[Token] = field(default_factory=list)


@dataclass
class Source:
    path: str
    module: str
    text: str
    is_global: bool = False
    # Identifiers of the form dialog (casefolded); None: the form context is unknown.
    dialog: frozenset[str] | None = None


@dataclass
class Parsed:
    source: Source
    tokens: list[Token]
    diagnostics: list[Diagnostic]
    pairs: dict[int, int] = field(default_factory=dict)
    symbols: dict[str, Symbol] = field(default_factory=dict)
    declarations: dict[int, tuple[int, Symbol]] = field(default_factory=dict)
    header_tokens: set[int] = field(default_factory=set)

    def report(self, token, rule, message, severity='error'):
        self.diagnostics.append(Diagnostic(self.source.path, self.source.module,
                                           token.line, token.column, rule, severity, message))


def lex(source: Source) -> tuple[list[Token], list[Diagnostic]]:
    """Keep source positions; comments and string contents can never become calls."""
    text = source.text.replace('\r\n', '\n').replace('\r', '\n')
    tokens, diagnostics = [], []
    i, line, column = 0, 1, 1

    def advance(end):
        nonlocal i, line, column
        chunk = text[i:end]
        count = chunk.count('\n')
        if count:
            line += count
            column = len(chunk.rsplit('\n', 1)[1]) + 1
        else:
            column += len(chunk)
        i = end

    while i < len(text):
        char = text[i]
        if char.isspace() or char == '\ufeff':
            advance(i + 1)
            continue
        if text.startswith('//', i):
            end = text.find('\n', i)
            advance(len(text) if end < 0 else end)
            continue
        if char == '#' or char == '&' and not text[text.rfind('\n', 0, i) + 1:i].strip():
            end = text.find('\n', i)
            end = len(text) if end < 0 else end
            diagnostics.append(Diagnostic(source.path, source.module, line, column,
                               'L7707', 'warning', 'Директива/аннотация не разбирается в профиле 7.7.'))
            advance(end)
            continue
        start, start_line, start_column = i, line, column
        if char == '"':
            end, closed = i + 1, False
            while end < len(text):
                if text[end] == '"':
                    if end + 1 < len(text) and text[end + 1] == '"':
                        end += 2
                        continue
                    end += 1
                    closed = True
                    break
                if text[end] == '\n':
                    nxt = end + 1
                    # Blank/comment-only lines may separate | continuations in 7.7.
                    while nxt < len(text):
                        if text[nxt] in ' \t\n':
                            nxt += 1
                        elif text.startswith('//', nxt):
                            newline = text.find('\n', nxt)
                            nxt = len(text) if newline < 0 else newline + 1
                        else:
                            break
                    if nxt >= len(text) or text[nxt] != '|':
                        break
                    end = nxt + 1
                    continue
                end += 1
            if not closed:
                diagnostics.append(Diagnostic(source.path, source.module, start_line,
                                   start_column, 'L7701', 'error', 'Незакрытая строка.'))
            tokens.append(Token('string', text[start:end], start_line, start_column))
            advance(end)
            continue
        if char.isalpha() or char == '_':
            end = i + 1
            while end < len(text) and (text[end].isalnum() or text[end] == '_'):
                end += 1
            kind = 'id'
        elif char.isdigit():
            end = i + 1
            while end < len(text) and (text[end].isdigit() or text[end] == '.'):
                end += 1
            kind = 'number'
        else:
            end, kind = i + 1, 'punct'
        tokens.append(Token(kind, text[start:end], start_line, start_column))
        advance(end)
    return tokens, diagnostics


def split_arguments(tokens: list[Token], start: int, end: int) -> list[list[Token]]:
    if start == end:
        return []
    parts, part, depth = [], [], 0
    for token in tokens[start:end]:
        if token.kind == 'punct' and token.text in ('(', '['):
            depth += 1
        elif token.kind == 'punct' and token.text in (')', ']'):
            depth -= 1
        if token.kind == 'punct' and token.text == ',' and depth == 0:
            parts.append(part)
            part = []
        else:
            part.append(token)
    parts.append(part)
    return parts


def parse(source: Source) -> Parsed:
    tokens, diagnostics = lex(source)
    result = Parsed(source, tokens, diagnostics)
    stack = []
    for i, token in enumerate(tokens):
        if token.kind != 'punct':
            continue
        if token.text in ('(', '['):
            stack.append(i)
        elif token.text in (')', ']'):
            expected = '(' if token.text == ')' else '['
            if not stack or tokens[stack[-1]].text != expected:
                result.report(token, 'L7702', f'Лишняя или несогласованная скобка {token.text}.')
            else:
                opening = stack.pop()
                result.pairs[opening] = i
    for i in stack:
        result.report(tokens[i], 'L7702', f'Не закрыта скобка {tokens[i].text}.')

    forwards = {}
    definitions = {}
    for i, token in enumerate(tokens):
        if token.kind != 'id' or token.key not in DECL or (i and tokens[i-1].text == '.'):
            continue
        if i + 2 >= len(tokens) or tokens[i+1].kind != 'id' or tokens[i+2].text != '(':
            result.report(token, 'L7703', 'Ожидалось имя процедуры/функции и список параметров.')
            continue
        end = result.pairs.get(i+2)
        if end is None:
            continue
        name = tokens[i+1]
        parts = split_arguments(tokens, i+3, end)
        optional = [any(t.text == '=' for t in part) for part in parts]
        params = [([t for t in (part[:[t.text for t in part].index('=')] if any(t.text == '=' for t in part)
                                else part) if t.kind == 'id'] or [None])[-1] for part in parts]
        last = end + 1
        flags = set()
        # "Экспорт = 1;" opening the body is an assignment, not a header flag.
        while (last < len(tokens) and tokens[last].key in ('экспорт', 'export', 'далее', 'forward')
               and (last + 1 == len(tokens) or tokens[last+1].text != '=')):
            flags.add(tokens[last].key)
            last += 1
        symbol = Symbol(name.text, name, DECL[token.key], optional,
                        bool(flags & {'экспорт', 'export'}), bool(flags & {'далее', 'forward'}),
                        [param for param in params if param is not None])
        result.header_tokens.update(range(i, last))
        result.declarations[i] = (last, symbol)
        target = forwards if symbol.forward else definitions
        if name.key in target:
            result.report(name, 'L7703', f'Повторное объявление {name.text}.')
        target[name.key] = symbol
    for key, symbol in forwards.items():
        definition = definitions.get(key)
        if definition is None:
            result.report(symbol.token, 'L7703', f'{symbol.name}: объявление «Далее» без реализации.')
        elif symbol.kind != definition.kind or len(symbol.optional) != len(definition.optional):
            result.report(definition.token, 'L7703', f'{symbol.name}: реализация не совпадает с объявлением «Далее».')
    result.symbols = {**forwards, **definitions}

    blocks = []
    for i, token in enumerate(tokens):
        if i in result.declarations:
            _, symbol = result.declarations[i]
            if not symbol.forward:
                if blocks:
                    result.report(token, 'L7703', 'Объявление процедуры/функции внутри незакрытого блока.')
                blocks.append((symbol.kind, token))
            continue
        if i in result.header_tokens or token.kind != 'id' or (i and tokens[i-1].text == '.'):
            continue
        key = token.key
        if key in ('если', 'if'):
            blocks.append(('if', token))
        elif key in ('цикл', 'do'):
            blocks.append(('loop', token))
        elif key in ('попытка', 'try'):
            blocks.append(('try', token))
        elif key in CLOSE:
            expected = CLOSE[key]
            if not blocks or blocks[-1][0] != expected:
                result.report(token, 'L7703', f'{token.text}: нет соответствующего открытого блока.')
            else:
                blocks.pop()
        elif key in ('иначе', 'else', 'иначеесли', 'elsif', 'elseif'):
            if not blocks or blocks[-1][0] != 'if':
                result.report(token, 'L7703', f'{token.text} вне блока Если.')
        elif key in ('исключение', 'except'):
            if not blocks or blocks[-1][0] != 'try':
                result.report(token, 'L7703', f'{token.text} вне блока Попытка.')
        elif key in ('прервать', 'break', 'продолжить', 'continue'):
            if not any(kind == 'loop' for kind, _ in blocks):
                result.report(token, 'L7703', f'{token.text} вне цикла.')
        elif (key in ('новый', 'new') and i+1 < len(tokens)
              and tokens[i+1].kind == 'id' and tokens[i+1].key not in KEYWORDS):
            result.report(token, 'L7707', 'Оператор Новый относится к 8.x; в 7.7 используется СоздатьОбъект().')
    for kind, token in blocks:
        result.report(token, 'L7703', f'Не закрыт блок {token.text} ({kind}).')
    return result


def check_calls(parsed: Parsed, globals_: dict[str, Symbol], builtins: set[str], strict=False):
    tokens = parsed.tokens
    visible = {**globals_, **parsed.symbols}
    for i, token in enumerate(tokens[:-1]):
        if (token.kind != 'id' or token.key in KEYWORDS or i in parsed.header_tokens
                or tokens[i+1].text != '(' or (i and tokens[i-1].text == '.')):
            continue
        symbol = visible.get(token.key)
        if symbol:
            end = parsed.pairs.get(i+1)
            if end is None:
                continue
            args = split_arguments(tokens, i+2, end)
            # Empty positional slots F(, X) are legal in 7.7.
            missing = [n+1 for n, optional in enumerate(symbol.optional)
                       if not optional and n >= len(args)]
            if len(args) > len(symbol.optional) or missing:
                detail = f'; отсутствуют обязательные аргументы {missing}' if missing else ''
                parsed.report(token, 'L7705', f'{token.text}: передано {len(args)}, параметров '
                              f'{len(symbol.optional)}{detail}.')
        elif token.key in builtins:
            continue
        elif token.key in KNOWN8:
            parsed.report(token, 'L7706', f'{token.text} — API 8.x; в 7.7 нужна собственная '
                          'процедура или реализация для 7.7. Доступное объявление не найдено.')
        else:
            parsed.report(token, 'L7704', f'Не разрешён вызов {token.text}: нет объявления в модуле, '
                          'переданных глобальных модулях или словаре 7.7. Возможен неполный контекст.',
                          'error' if strict else 'warning')


@dataclass
class Catalog:
    """Names from the packaged platform catalog (catalog77.json), casefolded."""
    reserved: set[str]
    calls: set[str]
    # Readable without declaration: probed global names and the form context.
    readable: set[str]
    # Largest parameter count of a Cyrillic method name; None: variadic signature.
    method_limits: dict[str, int | None]
    provenance: dict


_CATALOG: Catalog | None = None


def load_catalog() -> Catalog:
    global _CATALOG
    if _CATALOG is None:
        data = load_packaged()
        globals_ = json.loads(files('harness77').joinpath('lint77-globals.json').read_text(encoding='utf-8'))
        calls, readable, limits = set(), {n.casefold() for n in globals_['names']}, {}
        for item in data['items']:
            names = [n.casefold() for n in (item['name_ru'], item['name_en']) if n]
            if item['kind'] in ('global_function', 'method'):
                calls.update(names)
            if item['kind'] == 'attribute' and item['folder'].startswith('Контекст формы/') and '/Объект' not in item['folder']:
                readable.update(names)
            name = item['name_ru']
            if item['kind'] == 'method' and name and CYRILLIC.search(name):
                key, limit = name.casefold(), item['max_params']
                limits[key] = None if limit is None or limits.get(key, 0) is None else max(limit, limits.get(key, 0))
        provenance = {'platform_version': data['platform_version'],
                      'sources': [{'name': s['name'], 'sha256': s['sha256']} for s in data['sources']],
                      'globals_evidence': globals_['provenance']['evidence']}
        _CATALOG = Catalog({n.casefold() for n in data['reserved']['names']}, calls, readable, limits, provenance)
    return _CATALOG


def check_method_arity(parsed: Parsed, catalog: Catalog, strict=False):
    """L7709: a known method called with more arguments than any of its signatures."""
    tokens = parsed.tokens
    for i, token in enumerate(tokens[:-1]):
        if (token.kind != 'id' or not i or tokens[i-1].text != '.' or tokens[i+1].text != '('
                or catalog.method_limits.get(token.key) is None):
            continue
        end = parsed.pairs.get(i+1)
        if end is None:
            continue
        count, limit = len(split_arguments(tokens, i+2, end)), catalog.method_limits[token.key]
        if count > limit:
            parsed.report(token, 'L7709', f'{token.text}: передано {count}, в справочнике 7.7 у метода '
                          f'не больше {limit}. Компилятор это не проверяет; при исполнении часть объектов '
                          'отвечает «Слишком много параметров…», другие лишний аргумент игнорируют.',
                          'error' if strict else 'warning')


def check_line_length(parsed: Parsed):
    """L7710: physical lines, CR/LF and BOM excluded, longer than the guard."""
    text = parsed.source.text.lstrip('﻿').replace('\r\n', '\n').replace('\r', '\n')
    for number, line in enumerate(text.split('\n'), 1):
        if len(line) > LINE_LIMIT:
            parsed.diagnostics.append(Diagnostic(
                parsed.source.path, parsed.source.module, number, LINE_LIMIT + 1, 'L7710', 'warning',
                f'Длина строки {len(line)} больше защитного предела {LINE_LIMIT}. Конфигуратор 7.7 '
                'отказывает в такой строке («Одна из строк исходного текста превышает допустимые '
                'размеры»), исполнение её принимает; разбейте выражение на несколько строк.'))


def check_declarations(parsed: Parsed, catalog: Catalog, known: set[str], strict=False):
    """L7708 reserved names declared; L7711 reads of names not declared at that point.

    1C 7.7 declares a local by its first assignment in the text of the procedure;
    a read before it, in another procedure, or in the module body is "Переменная
    не определена". Module and procedure Перем, parameters, loop counters, the form
    dialog, global module exports and the probed global names declare names.
    """
    tokens, dialog = parsed.tokens, parsed.source.dialog
    # The probed global names belong to one configuration: another may add more.
    severity = 'error' if strict else 'warning'

    def reserved(token, role):
        if token.key in catalog.reserved:
            parsed.report(token, 'L7708', f'{token.text}: ключевое слово или встроенная функция 7.7 '
                          f'не может быть именем {role}.')

    for _, symbol in parsed.declarations.values():
        for param in symbol.params:
            reserved(param, 'параметра')
    closers = {'procedure': ('конецпроцедуры', 'endprocedure'), 'function': ('конецфункции', 'endfunction')}
    definitions = sorted((start, last, symbol) for start, (last, symbol) in parsed.declarations.items()
                         if not symbol.forward)
    module_vars: set[str] = set()

    def walk(start, end, declared):
        reported, prev, i = set(), None, start
        while i < end:
            token = tokens[i]
            if i in parsed.header_tokens:
                prev, i = None, i + 1
                continue
            if token.kind != 'id' or (prev is not None and prev.text in ('.', '~')):
                prev, i = token, i + 1
                continue
            begins = prev is None or prev.text in (';', ':') or (prev.kind == 'id' and prev.key in STATEMENT_START)
            following = tokens[i+1] if i + 1 < len(tokens) else None
            if begins and following is not None and following.text == '=':
                # Keywords too: "Не = 1;" and "Возврат = 1;" are rejected declarations in 7.7.
                reserved(token, 'переменной')
                declared.add(token.key)
                prev, i = token, i + 1
                continue
            if token.key in ('перем', 'var') and begins:
                # A name follows Перем or a comma; Экспорт after a name only marks it exported.
                depth, expect_name, i = 0, True, i + 1
                while i < end and tokens[i].text != ';':
                    item = tokens[i]
                    depth += {'[': 1, ']': -1}.get(item.text, 0)
                    if item.text == ',' and not depth:
                        expect_name = True
                    elif item.kind == 'id' and not depth and expect_name:
                        reserved(item, 'переменной')
                        declared.add(item.key)
                        expect_name = False
                    i += 1
                prev = tokens[i] if i < end else None
                i += 1
                continue
            if token.key in ('для', 'for') and following is not None and following.kind == 'id':
                reserved(following, 'счётчика цикла')
                declared.add(following.key)
                prev, i = following, i + 2
                continue
            if token.key in KEYWORDS or (following is not None and following.text == '('):
                pass
            # Reserved names are keywords or intrinsics: Контекст is read legitimately.
            elif (dialog is not None and token.key not in reported and token.key not in declared
                  and token.key not in module_vars and token.key not in dialog and token.key not in known
                  and token.key not in parsed.symbols and token.key not in catalog.reserved):
                reported.add(token.key)
                parsed.report(token, 'L7711', f'Переменная не определена ({token.text}): не параметр, '
                              'не Перем, не присвоена выше в этой процедуре, не реквизит диалога '
                              'и не глобальное имя. Глобальное имя конфигурации добавьте --allow/--globals.',
                              severity)
            prev, i = token, i + 1

    first = definitions[0][0] if definitions else len(tokens)
    walk(0, first, module_vars)
    tail = first
    for start, last, symbol in definitions:
        end = next((j for j in range(last, len(tokens)) if tokens[j].key in closers[symbol.kind]
                    and tokens[j-1].text != '.' and (j + 1 == len(tokens) or tokens[j+1].text != '=')),
                   len(tokens))
        walk(last, end, {param.key for param in symbol.params})
        tail = end + 1
    if definitions:
        walk(tail, len(tokens), set())


def exported_variables(parsed: Parsed) -> set[str]:
    """Module variables declared "Перем Имя Экспорт" before the first procedure."""
    tokens, names = parsed.tokens, set()
    first = min(parsed.declarations, default=len(tokens))
    i = 0
    while i < first:
        if tokens[i].key in ('перем', 'var') and (not i or tokens[i-1].text == ';'):
            depth, current, i = 0, None, i + 1
            while i < first and tokens[i].text != ';':
                token = tokens[i]
                depth += {'[': 1, ']': -1}.get(token.text, 0)
                if token.kind == 'id' and not depth:
                    if token.key in ('экспорт', 'export'):
                        names.update([current] if current else [])
                    else:
                        current = token.key
                i += 1
        i += 1
    return names


def ert_dialog(compound: CompoundFile) -> frozenset[str] | None:
    """Identifiers of the form dialog; None if the ERT has no readable dialog."""
    try:
        controls = dialog_controls(decode_dialog(compound.read_stream(compound.find_stream(DIALOG_STREAM))))
    except ErtError:
        return None
    return frozenset(control.identifier.casefold() for control in controls if control.identifier)


def dialog_context(path: Path) -> frozenset[str]:
    """Form context for text modules: an explicit ERT's dialog or form description, or an error."""
    if path.suffix.casefold() == '.json':
        from .form77 import dialog_identifiers, loads
        try:
            return dialog_identifiers(loads(path.read_bytes()))
        except ErtError as error:
            raise ValueError(f'{path.name}: {error}') from None
    if path.suffix.casefold() != '.ert':
        raise ValueError(f'Контекст формы задаётся файлом ERT или описанием формы JSON: {path}')
    dialog = ert_dialog(CompoundFile(path.read_bytes()))
    if dialog is None:
        raise ValueError(f'В {path.name} нет читаемого диалога формы.')
    return dialog


def cfb_paths(compound: CompoundFile) -> dict[int, str]:
    entries, paths, seen = compound.directory_entries, {}, set()
    pending = [(struct.unpack_from('<I', entries[0].raw, 76)[0], '')]
    while pending:
        index, parent = pending.pop()
        if index == 0xffffffff:
            continue
        if index >= len(entries) or index in seen:
            raise ErtError('Повреждено дерево каталогов OLE.')
        seen.add(index)
        entry = entries[index]
        left, right, child = struct.unpack_from('<III', entry.raw, 68)
        path = parent + '/' + entry.name if parent else entry.name
        paths[index] = path
        pending.extend([(left, parent), (right, parent)])
        if entry.object_type in (1, 5):
            pending.append((child, path))
    return paths


def load_sources(path: Path) -> list[Source]:
    path = path.resolve()
    if path.suffix.casefold() not in ('.ert', '.md'):
        # Existing decoder prints encoding notes; keep JSON stdout machine-readable.
        with contextlib.redirect_stdout(sys.stderr):
            text = decode_source_bytes(path.read_bytes(), path)
        return [Source(str(path), '', text)]
    compound = CompoundFile(path.read_bytes())
    paths = cfb_paths(compound)
    dialog = ert_dialog(compound) if path.suffix.casefold() == '.ert' else None
    result = []
    for entry in compound.directory_entries:
        if entry.object_type != 2 or entry.name != 'MD Programm text':
            continue
        module = paths.get(entry.entry_id, '')
        # TypedText also contains user help: those streams are prose, not code.
        if module.startswith('TypedText/') and not re.match(r'TypedText/(ModuleText|Transact)_Number\d+/', module):
            continue
        raw = compound.read_stream(entry)
        try:
            text = zlib.decompress(raw, -15).decode('cp1251')
        except (zlib.error, UnicodeError) as exc:
            raise ErtError(f'Не удалось прочитать модуль {module}: {exc}') from exc
        result.append(Source(str(path), module, text, module.startswith('TypedText/ModuleText_Number1/'), dialog))
    if not result:
        raise ErtError(f'В {path.name} не найдены модули кода.')
    return result


def collect_paths(inputs: list[str]) -> list[Path]:
    paths = set()
    for name in inputs:
        path = Path(name)
        if not path.exists():
            raise ValueError(f'Входной путь не существует: {path}')
        if path.is_dir():
            for item in path.rglob('*'):
                # .txt and .md must be specified explicitly: they can contain prose.
                if (item.is_file() and item.suffix.casefold() in ('.1s', '.bsl', '.ert')
                        and not any(p in ('.git', '.venv', '__pycache__') for p in item.relative_to(path).parts)):
                    paths.add(item.resolve())
        else:
            paths.add(path.resolve())
    if not paths:
        raise ValueError('Не найдено исходных файлов (.1s, .bsl, .ert); TXT и MD укажите явно.')
    return sorted(paths, key=str)


def load_builtins() -> set[str]:
    data = json.loads(files('harness77').joinpath('lint77-builtins.json').read_text(encoding='utf-8'))
    return {name.casefold() for name in data['functions']}


def analyze(sources: list[Source], global_sources=(), allow=(), strict=False) -> dict:
    parsed = [parse(source) for source in sources]
    external = [parse(source) for source in global_sources]
    # A local form's exported function is NOT a global function of the infobase.
    external_symbols = {}
    own_globals = {}
    for item in external + [item for item in parsed if item.source.is_global]:
        globals_ = (external_symbols if item in external
                    else own_globals.setdefault(item.source.path, {}))
        for key, symbol in item.symbols.items():
            if symbol.exported and not symbol.forward:
                if key in globals_ and globals_[key] != symbol:
                    raise ValueError(f'Неоднозначный глобальный контекст: {symbol.name}')
                globals_[key] = symbol
    catalog = load_catalog()
    builtins = load_builtins() | catalog.calls | {name.casefold() for name in allow}
    global_vars = set().union(*(exported_variables(item) for item in external
                                + [item for item in parsed if item.source.is_global]))
    known = catalog.readable | global_vars | set(external_symbols) | {name.casefold() for name in allow}
    diagnostics = []
    # Context that failed to parse must not silently produce a clean result.
    for item in external:
        diagnostics.extend(item.diagnostics)
    for item in parsed:
        visible_globals = {**external_symbols, **own_globals.get(item.source.path, {})}
        check_calls(item, visible_globals, builtins, strict)
        check_method_arity(item, catalog, strict)
        check_line_length(item)
        check_declarations(item, catalog, known | set(visible_globals), strict)
        diagnostics.extend(item.diagnostics)
    diagnostics.sort(key=lambda d: (d.path, d.module, d.line, d.column, d.rule))
    return {'schema_version': 1, 'tool': 'lint77', 'version': VERSION,
            'modules': len(parsed), 'global_context_modules': len(external),
            'form_context_modules': sum(item.source.dialog is not None for item in parsed),
            'catalog': catalog.provenance,
            'errors': sum(d.severity == 'error' for d in diagnostics),
            'warnings': sum(d.severity == 'warning' for d in diagnostics),
            'limitations': LIMITATIONS, 'diagnostics': [asdict(d) for d in diagnostics]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', help='Файлы TXT/1S/BSL/ERT/1Cv7.MD или каталоги исходников')
    parser.add_argument('--globals', action='append', default=[], metavar='FILE',
                        help='Глобальный модуль (текст) или MD; только экспортные функции. Можно повторять.')
    parser.add_argument('--allow', action='append', default=[], metavar='NAME',
                        help='Явно разрешить функцию внешнего контекста; можно повторять.')
    parser.add_argument('--dialog', type=Path, metavar='FORM.ert',
                        help='ERT или описание формы JSON: контекст формы текстовых модулей (для L7711).')
    parser.add_argument('--strict', action='store_true', help='Неизвестные вызовы считать ошибками')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    parser.add_argument('--output', type=Path, help='Записать отчёт в файл')
    parser.add_argument('--version', action='version', version=VERSION)
    args = parser.parse_args(argv)
    try:
        inputs = collect_paths(args.paths)
        contexts = [Path(name).resolve() for name in args.globals]
        if args.output:
            protected = inputs + contexts + ([args.dialog.resolve()] if args.dialog else []) + [
                Path(__file__).resolve()] + [Path(__file__).with_name(name).resolve() for name in (
                    'lint77-builtins.json', 'lint77-globals.json', 'catalog77.json')]
            if (args.output.resolve() in set(protected)
                    or (args.output.exists() and any(os.path.samefile(args.output, path) for path in protected))):
                raise ValueError('Путь отчёта совпадает с исходником, контекстом или файлом инструмента.')
        sources = [source for path in inputs for source in load_sources(path)]
        if args.dialog:
            dialog = dialog_context(args.dialog)
            for source in sources:
                if Path(source.path).suffix.casefold() not in ('.ert', '.md'):
                    source.dialog = dialog
        global_sources = []
        for path in contexts:
            loaded = load_sources(path)
            if path.suffix.casefold() == '.md':
                loaded = [source for source in loaded if source.is_global]
                if not loaded:
                    raise ValueError(f'Глобальный модуль не найден: {path}')
            elif path.suffix.casefold() == '.ert':
                raise ValueError('--globals принимает текст глобального модуля или MD, не ERT.')
            global_sources.extend(loaded)
        # Supplying the analyzed MD as its own context is harmless, avoid duplicates.
        own = {(source.path, source.module) for source in sources}
        global_sources = [source for source in global_sources if (source.path, source.module) not in own]
        report = analyze(sources, global_sources, args.allow, args.strict)
        if args.format == 'json':
            output = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        else:
            rows = []
            for d in report['diagnostics']:
                module = f"::{d['module']}" if d['module'] else ''
                rows.append(f"{d['path']}{module}:{d['line']}:{d['column']}: "
                            f"{d['severity']} {d['rule']}: {d['message']}")
            rows.append(f"lint77 {VERSION}: модулей {report['modules']}; ошибок {report['errors']}; "
                        f"предупреждений {report['warnings']}. Частичная проверка, не компилятор 1С.")
            output = '\n'.join(rows) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding='utf-8', newline='\n')
        else:
            sys.stdout.write(output)
        return 1 if report['errors'] else 0
    except (OSError, ValueError, ErtError, struct.error, RecursionError) as exc:
        error = {'schema_version': 1, 'tool': 'lint77', 'fatal_error': str(exc)}
        print(json.dumps(error, ensure_ascii=False) if args.format == 'json'
              else f'lint77: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
