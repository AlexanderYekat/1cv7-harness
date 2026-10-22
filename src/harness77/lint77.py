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
                         dialog_controls, parse_dialog)
from .moxcel77 import area_names, form_table, worksheets

VERSION = '0.5.0'
LIMITATIONS = [
    'Частичный разбор языка; отсутствие диагностик не означает успешную компиляцию 1С.',
    'Имена встроенных функций и методов — из каталога платформы 7.70.027; неизвестные вызовы '
    'по умолчанию — предупреждения.',
    'Типы, методы конфигурации, COM и внешних компонент, динамически исполняемый код не проверяются.',
    'Объявление переменных (L7711) проверяется только в модуле с известным контекстом: ERT, --dialog, '
    'формы, модули документов и глобальный модуль 1Cv7.MD (кроме форм операций, проводок и плана счетов).',
    'Имена объектов метаданных (L7712, L7713) проверяются только с метаданными базы: --metadata или '
    'модули самого 1Cv7.MD; имена форм, тексты запросов и строки вне аргументов функций — нет.',
    'Реквизиты (L7714) проверяются только у объекта, который переменная получает из '
    'СоздатьОбъект("Справочник|Документ|Регистр.<Вид>"), у реквизитов объекта в его модуле 1Cv7.MD '
    'и далее по ссылочным реквизитам; реквизиты значений неизвестного типа — нет.',
    'Внутри Если, условие которого проверяет имя через Метаданные, L7712-L7714 об этом имени молчат; '
    'проверка, сохранённая в переменную или с выходом из процедуры, не распознаётся.',
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
# Task 018: global attributes naming configuration objects -> classes of metadata77.
GLOBAL_OBJECTS = {'константа': 'Константа', 'перечисление': 'Перечисление', 'видысубконто': 'ВидСубконто',
                  'планысчетов': 'ПланСчетов'}
# Functions whose parameters take a type name or an object descriptor (syntax helper 7.70.027)
# and what 7.70.027 does with a kind the base lacks (task 018 probes); English names come
# from the catalog.
_LOST = '1С 7.7 ошибки не даёт: тип останется без вида (например, любой справочник)'
_LOST_UNPROBED = _LOST + ' — так ведут себя НоваяКолонка и ПолучитьПустоеЗначение; эта функция нативно не проверялась'
TYPE_FUNCTIONS = {
    'СоздатьОбъект': '1С 7.7 загружает модуль, исполнение строки прерывает «Неудачная попытка создания объекта»',
    'ОткрытьФорму': '1С 7.7 загружает модуль, исполнение строки прерывает «Неверно указан вид» '
                    '(«Неверный вид справочника», «Неверный вид журнала»)',
    'ОткрытьФормуМодально': '1С 7.7 загружает модуль, исполнение строки прерывает «Неверно указан вид»',
    'ОткрытьПодбор': '1С 7.7 загружает модуль, исполнение строки прерывает «Неверный вид справочника»',
    'ПолучитьПустоеЗначение': _LOST, 'НоваяКолонка': _LOST, 'ВставитьКолонку': _LOST,
    'УстановитьПараметрыКолонки': _LOST,
    'ПравоДоступа': '1С 7.7 ошибки не даёт: право проверяется для объекта, которого нет',
    'НазначитьТип': _LOST_UNPROBED, 'ВвестиЗначение': _LOST_UNPROBED, 'УстановитьРеквизитСправочника': _LOST_UNPROBED,
}
# "Type." of such a string -> classes its kind may belong to; "Журнал.<вид документа>" opens
# the journal of that kind, "Журнал.Подчиненные" the subordinate documents.
TYPE_PREFIXES = {'справочник': ('Справочник',), 'элемент': ('Справочник',), 'документ': ('Документ',),
                 'журнал': ('Журнал', 'Документ'), 'перечисление': ('Перечисление',), 'счет': ('ПланСчетов',),
                 'плансчетов': ('ПланСчетов',), 'регистр': ('Регистр',), 'отчет': ('Отчет',),
                 'обработка': ('Обработка',)}
TYPE_STRING = re.compile(r'"([A-Za-zА-Яа-яЁё]+)\.([A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*)([.#][^"]*)?"\Z')
# Task 019: objects СоздатьОбъект("<Тип>.<Вид>") makes whose attributes lint follows; the
# catalog's "<Класс>/Атрибуты" are the attributes every object of the class has.
OBJECT_CLASSES = {'справочник': 'Справочник', 'документ': 'Документ', 'регистр': 'Регистр'}
ATTRIBUTE_CLASSES = set(OBJECT_CLASSES.values())
# Task 020: catalog folders of the attributes a module of an object reads bare, by its class.
CONTEXT_ATTRIBUTES = {'Справочник': 'Справочник/Атрибуты', 'Документ': 'Документ/Атрибуты',
                      'Регистр': 'Регистр/Атрибуты', 'Журнал': 'Документ/Модуль формы журнала документов/Атрибуты'}
# The form's table attribute: readable in a form that lists worksheets, not in one without (task 020).
FORM_TABLE = {'таблица', 'table'}
# 1Cv7.MD forms whose context (an operation, its entries, a chart of accounts) lint does not model.
UNMODELLED_FORMS = {'Operation', 'OperationList', 'ProvList', 'AccountChart', 'AccountChartList'}
# Метаданные.<Класс>("Имя") in a condition of Если guards an object; .<Член>("Имя") after it, or
# Метаданные.ОбщийРеквизитДокумента("Имя"), an attribute or an enumeration value.
GUARD_CLASSES = {name.casefold(): name for name in ('Константа', 'Справочник', 'Документ', 'Перечисление', 'Регистр',
                                                    'Отчет', 'Обработка', 'Журнал', 'ПланСчетов', 'ВидСубконто')}
GUARD_MEMBERS = {'реквизит', 'реквизитшапки', 'реквизиттабличнойчасти', 'измерение', 'ресурс', 'значение'}
GUARD_GENERAL = 'общийреквизитдокумента'
NAME_STRING = re.compile(r'"([A-Za-zА-Яа-яЁё_][0-9A-Za-zА-Яа-яЁё_]*)"\Z')
STATEMENT_END = {'конецесли', 'endif', 'иначе', 'else', 'иначеесли', 'elsif', 'elseif', 'конеццикла', 'enddo',
                 'конецпопытки', 'endtry', 'исключение', 'except', 'конецпроцедуры', 'endprocedure',
                 'конецфункции', 'endfunction'}


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
    # metadata77.Metadata of the base the module runs on (L7712-L7714); None: unknown.
    metadata: object | None = None
    # (class, kind) of the object whose form or module this 1Cv7.MD module is (task 020); None: no object.
    owner: tuple[str, str] | None = None


@dataclass
class Parsed:
    source: Source
    tokens: list[Token]
    diagnostics: list[Diagnostic]
    pairs: dict[int, int] = field(default_factory=dict)
    symbols: dict[str, Symbol] = field(default_factory=dict)
    declarations: dict[int, tuple[int, Symbol]] = field(default_factory=dict)
    header_tokens: set[int] = field(default_factory=set)
    # Findings of L7712-L7714 left out under a Метаданные check; attributes L7714 compared (task 019).
    guarded: int = 0
    attributes_checked: int = 0
    _guards: list | None = None

    def report(self, token, rule, message, severity='error'):
        self.diagnostics.append(Diagnostic(self.source.path, self.source.module,
                                           token.line, token.column, rule, severity, message))

    def is_guarded(self, index, keys):
        """Whether the token is inside an Если whose condition checks one of these names in Метаданные."""
        if self._guards is None:
            self._guards = metadata_guards(self.tokens)
        if any(start <= index <= end and guards & keys for start, end, guards in self._guards):
            self.guarded += 1
            return True
        return False


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
        # A date literal '01.01.2000' (task 020: 'ОК' in Торговля+Склад is one too, not a name).
        close = -1
        if char == "'":
            line_end = text.find('\n', i)
            close = text.find("'", i + 1, len(text) if line_end < 0 else line_end)
        if close > 0:
            tokens.append(Token('date', text[start:close + 1], start_line, start_column))
            advance(close + 1)
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
    # Casefolded Russian and English names of TYPE_FUNCTIONS -> the Russian name.
    type_functions: dict[str, str] = field(default_factory=dict)
    # Attributes every object of a class has (Код, НомерДок…), casefolded: class -> names.
    object_attributes: dict[str, set[str]] = field(default_factory=dict)
    # TYPE_FUNCTIONS that are only global functions: X.СоздатьОбъект(…) is another base's (V77.CreateObject).
    global_type_functions: set[str] = field(default_factory=set)


_CATALOG: Catalog | None = None


def load_catalog() -> Catalog:
    global _CATALOG
    if _CATALOG is None:
        data = load_packaged()
        globals_ = json.loads(files('harness77').joinpath('lint77-globals.json').read_text(encoding='utf-8'))
        calls, readable, limits = set(), {n.casefold() for n in globals_['names']}, {}
        type_functions = {name.casefold(): name for name in TYPE_FUNCTIONS}
        object_attributes = {name: set() for name in CONTEXT_ATTRIBUTES}
        classes = {folder: name for name, folder in CONTEXT_ATTRIBUTES.items()}
        kinds = {}
        for item in data['items']:
            names = [n.casefold() for n in (item['name_ru'], item['name_en']) if n]
            if item['kind'] == 'attribute' and item['folder'] in classes:
                object_attributes[classes[item['folder']]].update(names)
            if item['kind'] in ('global_function', 'method'):
                calls.update(names)
                russian = type_functions.get((item['name_ru'] or '').casefold())
                if russian:
                    type_functions.update(dict.fromkeys(names, russian))
                    kinds.setdefault(russian, set()).add(item['kind'])
            if item['kind'] == 'attribute' and item['folder'].startswith('Контекст формы/') and '/Объект' not in item['folder']:
                # Таблица belongs to a form with tables only (task 020): ert_dialog adds it there.
                readable.update(set(names) - FORM_TABLE)
            name = item['name_ru']
            if item['kind'] == 'method' and name and CYRILLIC.search(name):
                key, limit = name.casefold(), item['max_params']
                limits[key] = None if limit is None or limits.get(key, 0) is None else max(limit, limits.get(key, 0))
        provenance = {'platform_version': data['platform_version'],
                      'sources': [{'name': s['name'], 'sha256': s['sha256']} for s in data['sources']],
                      'globals_evidence': globals_['provenance']['evidence']}
        _CATALOG = Catalog({n.casefold() for n in data['reserved']['names']}, calls, readable, limits, provenance,
                           type_functions, object_attributes,
                           {name for name, found in kinds.items() if found == {'global_function'}})
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

    (begin, end, _), *bodies = scopes(parsed)
    walk(begin, end, module_vars)
    for begin, end, symbol in bodies:
        walk(begin, end, {param.key for param in symbol.params} if symbol else set())


def scopes(parsed: Parsed) -> list[tuple[int, int, Symbol | None]]:
    """Token ranges (begin, end, symbol): the module head, each procedure body, the main program.

    The head runs up to the first procedure (the whole module without procedures); the
    main program, symbol None as the head's, follows the last one.
    """
    tokens = parsed.tokens
    closers = {'procedure': ('конецпроцедуры', 'endprocedure'), 'function': ('конецфункции', 'endfunction')}
    definitions = sorted((start, last, symbol) for start, (last, symbol) in parsed.declarations.items()
                         if not symbol.forward)
    first = definitions[0][0] if definitions else len(tokens)
    result, tail = [(0, first, None)], first
    for start, last, symbol in definitions:
        end = next((j for j in range(last, len(tokens)) if tokens[j].key in closers[symbol.kind]
                    and tokens[j-1].text != '.' and (j + 1 == len(tokens) or tokens[j+1].text != '=')),
                   len(tokens))
        result.append((last, end, symbol))
        tail = end + 1
    if definitions:
        result.append((tail, len(tokens), None))
    return result


def check_metadata_names(parsed: Parsed, catalog: Catalog, own: set[str], strict=False):
    """L7712 objects through global attributes, L7713 "Type.Kind" arguments, absent from the base's metadata.

    Both are late bound in 7.7 (docs/tasks/018-metadata-names-acceptance.md): the
    module loads, and the line fails when it runs or, for type names of columns and
    empty values, quietly keeps the type without its kind. A processing may serve
    several configurations and check Метаданные.<Класс>("Имя").Выбран() first, hence
    warnings; inside an Если that checks the name they are left out (task 019).
    """
    metadata = parsed.source.metadata
    if metadata is None:
        return
    objects, tokens = metadata.objects(), parsed.tokens
    severity = 'error' if strict else 'warning'
    base = metadata.describe()

    def follows(index, text):
        return index < len(tokens) and tokens[index].text == text

    for i, token in enumerate(tokens):
        if token.kind != 'id':
            continue
        method = bool(i) and tokens[i-1].text == '.'
        if (token.key in GLOBAL_OBJECTS and not method and follows(i + 1, '.') and i + 2 < len(tokens)
                and tokens[i+2].kind == 'id' and not follows(i + 3, '(')):
            name, kind = tokens[i+2], GLOBAL_OBJECTS[token.key]
            if name.key not in objects[kind]:
                if parsed.is_guarded(i, {(kind, name.key)}):
                    continue
                parsed.report(name, 'L7712', f'{token.text}.{name.text}: в метаданных {base} нет объекта '
                              f'{kind}.{name.text}. 1С 7.7 загружает модуль, а исполнение строки прерывает '
                              f'«Поле агрегатного объекта не обнаружено ({name.text})».', severity)
            elif (kind == 'Перечисление' and follows(i + 3, '.') and i + 4 < len(tokens)
                  and tokens[i+4].kind == 'id' and not follows(i + 5, '(')):
                value = tokens[i+4]
                if value.key not in metadata.enum_values(name.text) and not parsed.is_guarded(i, {(None, value.key)}):
                    parsed.report(value, 'L7712', f'{token.text}.{name.text}.{value.text}: у перечисления '
                                  f'{objects[kind][name.key]} в метаданных {base} нет значения {value.text}. '
                                  '1С 7.7 загружает модуль, а исполнение строки прерывает «Поле агрегатного '
                                  f'объекта не обнаружено ({value.text})».', severity)
        elif (token.key in catalog.type_functions and follows(i + 1, '(') and (method or token.key not in own)
              and not (method and catalog.type_functions[token.key] in catalog.global_type_functions)):
            end = parsed.pairs.get(i + 1)
            for part in split_arguments(tokens, i + 2, end) if end is not None else ():
                match = TYPE_STRING.match(part[0].text) if len(part) == 1 and part[0].kind == 'string' else None
                classes = TYPE_PREFIXES.get(match.group(1).casefold()) if match else None
                if not classes or match.group(1).casefold() == 'журнал' and match.group(2).casefold() == 'подчиненные':
                    continue
                if not any(match.group(2).casefold() in objects[kind] for kind in classes) and not parsed.is_guarded(
                        i, {(kind, match.group(2).casefold()) for kind in classes}):
                    where = ' или '.join(f'{kind}.{match.group(2)}' for kind in classes)
                    outcome = TYPE_FUNCTIONS[catalog.type_functions[token.key]]
                    parsed.report(part[0], 'L7713', f'{token.text}({part[0].text}): в метаданных {base} нет '
                                  f'объекта {where}. {outcome}.', severity)


def metadata_guards(tokens: list[Token]) -> list[tuple[int, int, set]]:
    """Если statements whose conditions check names in Метаданные: (Если, КонецЕсли, guards).

    A guard is (class, casefolded name) of Метаданные.<Класс>("Имя"), or (None, casefolded
    name) of an attribute or value checked after it (.Реквизит("Имя"), .Значение("Имя")…)
    and of Метаданные.ОбщийРеквизитДокумента("Имя"). Every branch of the statement counts:
    the check may be "= 1" or "= 0".
    """
    def at(j, text):
        return j < len(tokens) and tokens[j].text == text

    def name(j):
        match = NAME_STRING.match(tokens[j].text) if j < len(tokens) and tokens[j].kind == 'string' else None
        return match.group(1).casefold() if match else None

    regions, stack, condition = [], [], None
    for i, token in enumerate(tokens):
        if token.kind != 'id' or (i and tokens[i-1].text == '.'):
            continue
        if token.key in ('если', 'if'):
            stack.append((i, set()))
            condition = stack[-1][1]
        elif token.key in ('иначеесли', 'elsif', 'elseif') and stack:
            condition = stack[-1][1]
        elif token.key in ('тогда', 'then'):
            condition = None
        elif token.key in ('конецесли', 'endif') and stack:
            start, guards = stack.pop()
            if guards:
                regions.append((start, i, guards))
        elif (condition is not None and token.key in ('метаданные', 'metadata') and at(i + 1, '.')
              and i + 2 < len(tokens) and at(i + 3, '(') and name(i + 4) and at(i + 5, ')')):
            member = tokens[i+2].key
            if member == GUARD_GENERAL:
                condition.add((None, name(i + 4)))
            elif member in GUARD_CLASSES:
                condition.add((GUARD_CLASSES[member], name(i + 4)))
                if (at(i + 6, '.') and i + 7 < len(tokens) and tokens[i+7].key in GUARD_MEMBERS and at(i + 8, '(')
                        and name(i + 9) and at(i + 10, ')')):
                    condition.add((None, name(i + 9)))
    return regions


def check_attributes(parsed: Parsed, catalog: Catalog, own: set[str], known: set[str], strict=False):
    """L7714: an attribute of an object made by СоздатьОбъект("<Тип>.<Вид>") absent from the base's metadata.

    A name holds the object when every assignment to it in its scope is that call with one
    kind: a local of a procedure or of the main program, or a module variable assigned only
    so in every procedure. A parameter, a loop counter, a form attribute, a global name or a
    name passed whole to a procedure of the module may hold anything else and is not followed.
    Reference attributes lead on: Док.Сотрудник.Должность checks the catalog of Сотрудник.
    In a module of an object (task 020) its own reference attributes start the chain bare:
    Контрагент.ИНН in a document module checks the catalog of Контрагент.
    """
    metadata, owner = parsed.source.metadata, parsed.source.owner
    if metadata is None:
        return
    tokens, severity, base = parsed.tokens, 'error' if strict else 'warning', metadata.describe()
    owned = metadata.attributes(*owner) if owner and owner[0] in ATTRIBUTE_CLASSES else {}
    module_vars, dialog = module_variables(parsed), parsed.source.dialog or frozenset()
    # Binding -> (class, kind, assignment token) of the object it holds; None: anything else.
    held, uses = {}, []

    def follows(index, text):
        return index < len(tokens) and tokens[index].text == text

    def created(i):
        """(class, kind) of "= СоздатьОбъект("<Тип>.<Вид>")" ending the statement after tokens[i], or None."""
        call = tokens[i+2] if i + 2 < len(tokens) else None
        if (call is None or call.kind != 'id' or catalog.type_functions.get(call.key) != 'СоздатьОбъект'
                or call.key in own or not follows(i + 3, '(')):
            return None
        end = parsed.pairs.get(i + 3)
        parts = split_arguments(tokens, i + 4, end) if end is not None else []
        match = TYPE_STRING.match(parts[0][0].text) if len(parts) == 1 and len(parts[0]) == 1 \
            and parts[0][0].kind == 'string' else None
        if (not match or match.group(3) or match.group(1).casefold() not in OBJECT_CLASSES
                or not (end + 1 == len(tokens) or tokens[end+1].text == ';' or tokens[end+1].key in STATEMENT_END)):
            return None
        cls = OBJECT_CLASSES[match.group(1).casefold()]
        kind = metadata.objects()[cls].get(match.group(2).casefold())
        return (cls, kind) if kind else None

    def assign(name, value):
        if name is not None:
            previous = held.get(name, value)
            held[name] = previous if previous and value and previous[:2] == value[:2] else None

    for number, (begin, end, symbol) in enumerate(scopes(parsed)):
        local = {param.key for param in symbol.params} if symbol else set()
        for key in local:
            held[('local', number, key)] = None
        starts, prev = [], None
        for i in range(begin, end):
            if i in parsed.header_tokens:
                prev = None
                continue
            if prev is None or prev.text in (';', ':') or (prev.kind == 'id' and prev.key in STATEMENT_START):
                starts.append(i)
                if symbol and tokens[i].key in ('перем', 'var'):
                    # A name follows Перем or a comma, as check_declarations reads it.
                    j, depth, expect = i + 1, 0, True
                    while j < end and tokens[j].text != ';':
                        depth += {'[': 1, ']': -1}.get(tokens[j].text, 0)
                        if tokens[j].text == ',' and not depth:
                            expect = True
                        elif tokens[j].kind == 'id' and not depth and expect:
                            local.add(tokens[j].key)
                            expect = False
                        j += 1
            prev = tokens[i]

        def bound(key):
            """The variable a name in this scope stands for; None: a global or form name."""
            if key in local:
                return ('local', number, key)
            if key in module_vars:
                return ('module', key)
            if key in owned:
                return ('owner', key)
            if key in known or key in dialog:
                return None
            return ('module', key) if not number else ('local', number, key)

        for i in starts:
            token = tokens[i]
            if token.kind == 'id' and token.key in ('для', 'for') and i + 1 < end and tokens[i+1].kind == 'id':
                assign(bound(tokens[i+1].key), None)
            elif token.kind == 'id' and token.key not in KEYWORDS and follows(i + 1, '='):
                kind = created(i)
                assign(bound(token.key), kind and (*kind, token))
        for i in range(begin, end):
            token = tokens[i]
            if token.kind != 'id' or i in parsed.header_tokens or (i and tokens[i-1].text in ('.', '~')):
                continue
            if token.key in own and follows(i + 1, '(') and parsed.pairs.get(i + 1) is not None:
                for part in split_arguments(tokens, i + 2, parsed.pairs[i + 1]):
                    if len(part) == 1 and part[0].kind == 'id':
                        assign(bound(part[0].key), None)
            elif follows(i + 1, '.') and not follows(i + 3, '(') and bound(token.key):
                uses.append((i, bound(token.key)))
    for key in held:
        if key[0] == 'module' and module_vars.get(key[1]):
            held[key] = None
    for i, key in uses:
        if key[0] == 'owner':
            if owned[key[1]].target is None:
                continue
            (cls, kind), via = owned[key[1]].target, f' (реквизит {tokens[i].text})'
            origin = f'{tokens[i].text} — реквизит {owner[0]}.{owner[1]}, чей это модуль'
        elif held.get(key):
            cls, kind, made = held[key]
            via, origin = '', f'{tokens[i].text} — СоздатьОбъект("{cls}.{kind}") в строке {made.line}'
        else:
            continue
        j, path = i, [tokens[i].text]
        while (follows(j + 1, '.') and j + 2 < len(tokens) and tokens[j+2].kind == 'id'
               and not follows(j + 3, '(')):
            name = tokens[j+2]
            path.append(name.text)
            parsed.attributes_checked += 1
            if name.key in catalog.object_attributes[cls]:
                break
            attribute = metadata.attributes(cls, kind).get(name.key)
            if attribute is None:
                if not parsed.is_guarded(i, {(None, name.key)}):
                    parsed.report(name, 'L7714', f'{".".join(path)}: у объекта {cls}.{kind}{via} в метаданных '
                                  f'{base} нет реквизита {name.text}; {origin}. 1С 7.7 загружает модуль, '
                                  'а исполнение строки прерывает «Поле агрегатного объекта не обнаружено '
                                  f'({name.text})».', severity)
                break
            if attribute.target is None:
                break
            (cls, kind), via = attribute.target, f' (реквизит {name.text})'
            j += 2


def module_variables(parsed: Parsed) -> dict[str, bool]:
    """Module variables declared "Перем Имя [Экспорт]" before the first procedure: name → exported."""
    tokens, names = parsed.tokens, {}
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
                        if current:
                            names[current] = True
                    else:
                        current = token.key
                        names.setdefault(current, False)
                i += 1
        i += 1
    return names


def exported_variables(parsed: Parsed) -> set[str]:
    """Module variables declared "Перем Имя Экспорт" before the first procedure."""
    return {name for name, exported in module_variables(parsed).items() if exported}


def ert_dialog(compound: CompoundFile, entry=None) -> frozenset[str] | None:
    """Names the form's module reads without declaration (the ERT's form or this dialog entry's).

    The dialog's controls and list columns (Browser/Fixed, the identifier is field 7), Таблица
    if the form lists worksheets, and the named areas of the form's table, the worksheet its
    Container.Profile names (task 020). None if the dialog is unreadable or that table is not
    a worksheet this reader knows.
    """
    try:
        entry = compound.find_stream(DIALOG_STREAM) if entry is None else entry
        text = decode_dialog(compound.read_stream(entry))
        names = {control.identifier for control in dialog_controls(text)}
        for section in parse_dialog(text)[1:]:
            if isinstance(section, list) and section[:1] == ['Browser']:
                for item in section[1:]:
                    if isinstance(item, list) and item[:1] == ['Fixed']:
                        names.update(record[7] for record in item[1:]
                                     if isinstance(record, list) and len(record) > 7 and isinstance(record[7], str))
    except ErtError:
        return None
    paths = cfb_paths(compound)
    folder = paths.get(entry.entry_id, '').rpartition('/')[0]
    streams = {path: item for item_id, path in paths.items()
               for item in [compound.directory_entries[item_id]] if item.object_type == 2}

    def sibling(name):
        found = streams.get(f'{folder}/{name}' if folder else name)
        return None if found is None else compound.read_stream(found)

    contents = sibling('Container.Contents') or b''
    if worksheets(contents):
        names.update(FORM_TABLE)
    worksheet = form_table(contents, sibling('Container.Profile') or b'')
    if worksheet is not None:
        table = sibling(worksheet)
        areas = area_names(table) if table is not None else None
        if areas is None:
            return None
        names.update(areas)
    # Only identifiers are names a module reads; an area "200" or a column without one adds nothing.
    return frozenset(name.casefold() for name in names if name)


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


def load_sources(path: Path, own_metadata_names=True) -> list[Source]:
    """Modules of a text, ERT or 1Cv7.MD; a 1Cv7.MD's own object names unless only its exports are wanted."""
    path = path.resolve()
    if path.suffix.casefold() not in ('.ert', '.md'):
        # Existing decoder prints encoding notes; keep JSON stdout machine-readable.
        with contextlib.redirect_stdout(sys.stderr):
            text = decode_source_bytes(path.read_bytes(), path)
        return [Source(str(path), '', text)]
    data = path.read_bytes()
    compound = CompoundFile(data)
    paths = cfb_paths(compound)
    is_md = path.suffix.casefold() == '.md'
    dialog = None if is_md else ert_dialog(compound)
    # Modules of a configuration run on its own metadata (L7712-L7714).
    metadata = own_metadata(compound, data, path) if own_metadata_names and is_md else None
    streams = {paths[entry.entry_id]: entry for entry in compound.directory_entries
               if entry.object_type == 2 and entry.entry_id in paths}
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
        owner = None
        if is_md:
            dialog, owner = md_context(compound, streams, module, metadata)
        result.append(Source(str(path), module, text, module.startswith('TypedText/ModuleText_Number1/'), dialog,
                             metadata, owner))
    if not result:
        raise ErtError(f'В {path.name} не найдены модули кода.')
    return result


def md_context(compound: CompoundFile, streams: dict, module: str, metadata):
    """(dialog, owner) of a 1Cv7.MD module (task 020): a form's dialog is its folder's Dialog Stream,
    a document module (Transact) and the global module have an empty one; the owner is the
    object it belongs to."""
    match = re.match(r'(?:\w+/)?(\w+?)_Number(\d+)/', module)
    if not match:
        return None, None
    folder, number = match.group(1), int(match.group(2))
    if folder in UNMODELLED_FORMS:
        return None, None
    owner = metadata.owner(folder, number) if metadata is not None else None
    sibling = streams.get(module.rsplit('/', 1)[0] + '/' + DIALOG_STREAM)
    if sibling is not None:
        return ert_dialog(compound, sibling), owner
    return (frozenset() if folder in ('Transact', 'ModuleText') else None), owner


def own_metadata(compound: CompoundFile, data: bytes, path: Path):
    """The names of a 1Cv7.MD for its own modules; None if it has no metadata stream."""
    from .metadata77 import STREAM, Metadata
    if not any(entry.object_type == 2 and entry.name == STREAM for entry in compound.directory_entries):
        return None
    return base_metadata(Metadata(data, path))


def base_metadata(metadata):
    """Metadata whose object and attribute names have been read: an unknown record refuses the analysis up front."""
    metadata.objects()
    metadata.attributes('Справочник', '')
    return metadata


def load_metadata(path: Path):
    """--metadata: the 1Cv7.MD of the base the modules run on."""
    from .metadata77 import load
    if path.suffix.casefold() != '.md':
        raise ValueError(f'Метаданные базы задаются файлом 1Cv7.MD: {path}')
    return base_metadata(load(path))


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


def owner_names(source: Source, catalog: Catalog) -> set[str]:
    """Names a module of an object reads without declaration (task 020): its attributes and its class's."""
    if source.owner is None or source.metadata is None:
        return set()
    cls, kind = source.owner
    own = source.metadata.attributes(cls, kind) if cls in ATTRIBUTE_CLASSES else None
    return set(own or ()) | catalog.object_attributes[cls]


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
        check_declarations(item, catalog, known | set(visible_globals) | owner_names(item.source, catalog), strict)
        check_metadata_names(item, catalog, set(visible_globals) | set(item.symbols), strict)
        check_attributes(item, catalog, set(visible_globals) | set(item.symbols), known | set(visible_globals), strict)
        diagnostics.extend(item.diagnostics)
    diagnostics.sort(key=lambda d: (d.path, d.module, d.line, d.column, d.rule))
    contexts = {}
    for item in parsed:
        if item.source.metadata is not None:
            public = item.source.metadata.public()
            contexts.setdefault((public['path'], public['sha256']), public)
    return {'schema_version': 1, 'tool': 'lint77', 'version': VERSION,
            'modules': len(parsed), 'global_context_modules': len(external),
            'form_context_modules': sum(item.source.dialog is not None for item in parsed),
            'md_context_modules': sum(item.source.dialog is not None and Path(item.source.path).suffix.casefold() == '.md'
                                      for item in parsed),
            'metadata_context_modules': sum(item.source.metadata is not None for item in parsed),
            'metadata': list(contexts.values()),
            'metadata_guarded': sum(item.guarded for item in parsed),
            'attributes_checked': sum(item.attributes_checked for item in parsed),
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
    parser.add_argument('--metadata', type=Path, metavar='1Cv7.MD',
                        help='Метаданные базы, на которой исполняются модули TXT/1S/BSL/ERT (для L7712–L7714); '
                             'модули самого 1Cv7.MD сверяются с его метаданными.')
    parser.add_argument('--strict', action='store_true', help='Неизвестные вызовы считать ошибками')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    parser.add_argument('--output', type=Path, help='Записать отчёт в файл')
    parser.add_argument('--version', action='version', version=VERSION)
    args = parser.parse_args(argv)
    try:
        inputs = collect_paths(args.paths)
        contexts = [Path(name).resolve() for name in args.globals]
        if args.output:
            protected = inputs + contexts + ([args.dialog.resolve()] if args.dialog else []) + (
                [args.metadata.resolve()] if args.metadata else []) + [
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
        if args.metadata:
            metadata = load_metadata(args.metadata)
            for source in sources:
                if Path(source.path).suffix.casefold() != '.md':
                    source.metadata = metadata
        global_sources = []
        for path in contexts:
            loaded = load_sources(path, own_metadata_names=False)
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
