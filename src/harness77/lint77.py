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

from .ert_module import CompoundFile, ErtError, decode_source_bytes

VERSION = '0.1.0'
LIMITATIONS = [
    'Частичный разбор языка; отсутствие диагностик не означает успешную компиляцию 1С.',
    'Словарь встроенных функций неполон: неизвестные вызовы по умолчанию — предупреждения.',
    'Методы объектов, COM, реквизиты форм, типы и динамически исполняемый код не проверяются.',
    'Доступность известных встроенных функций в конкретном контексте модуля не проверяется.',
    'Проводки, запросы и корректность бухгалтерского учета не проверяются.',
]
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


@dataclass
class Source:
    path: str
    module: str
    text: str
    is_global: bool = False


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
        optional = [any(t.text == '=' for t in part) for part in split_arguments(tokens, i+3, end)]
        last = end + 1
        flags = set()
        while last < len(tokens) and tokens[last].key in ('экспорт', 'export', 'далее', 'forward'):
            flags.add(tokens[last].key)
            last += 1
        symbol = Symbol(name.text, name, DECL[token.key], optional,
                        bool(flags & {'экспорт', 'export'}), bool(flags & {'далее', 'forward'}))
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
        result.append(Source(str(path), module, text, module.startswith('TypedText/ModuleText_Number1/')))
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
    builtins = load_builtins() | {name.casefold() for name in allow}
    diagnostics = []
    # Context that failed to parse must not silently produce a clean result.
    for item in external:
        diagnostics.extend(item.diagnostics)
    for item in parsed:
        visible_globals = {**external_symbols, **own_globals.get(item.source.path, {})}
        check_calls(item, visible_globals, builtins, strict)
        diagnostics.extend(item.diagnostics)
    diagnostics.sort(key=lambda d: (d.path, d.module, d.line, d.column, d.rule))
    return {'schema_version': 1, 'tool': 'lint77', 'version': VERSION,
            'modules': len(parsed), 'global_context_modules': len(external),
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
    parser.add_argument('--strict', action='store_true', help='Неизвестные вызовы считать ошибками')
    parser.add_argument('--format', choices=('text', 'json'), default='text')
    parser.add_argument('--output', type=Path, help='Записать отчёт в файл')
    parser.add_argument('--version', action='version', version=VERSION)
    args = parser.parse_args(argv)
    try:
        inputs = collect_paths(args.paths)
        contexts = [Path(name).resolve() for name in args.globals]
        if args.output:
            protected = inputs + contexts + [Path(__file__).resolve(),
                                             Path(__file__).with_name('lint77-builtins.json').resolve()]
            if (args.output.resolve() in set(protected)
                    or (args.output.exists() and any(os.path.samefile(args.output, path) for path in protected))):
                raise ValueError('Путь отчёта совпадает с исходником, контекстом или файлом инструмента.')
        sources = [source for path in inputs for source in load_sources(path)]
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
