# MCP-сервер: пробы задачи 014

[Задание](../../docs/tasks/014-mcp-server.md). Продукт — `harness77 mcp`
(`src/harness77/mcp77.py`); здесь — проверки настоящими клиентами и настоящей 1С.

- `verify_mcp77.py` — официальный клиент Python SDK `mcp` 2.3.0: `conformance` (C1:
  каждый переносимый инструмент на локальном корпусе рядом с той же командой CLI),
  `run` (N1, N2: запуск через MCP с прогрессом и `ping`, с `--cancel-after-s` — отмена
  вызова), `close` (N3: свой клиент без снятия дерева закрывает stdin во время запуска),
  `cli-run` (тот же запуск напрямую через CLI).
- `claude_probe77.py` — Claude Code без интерфейса (`claude -p`): `lint` (C2: агент
  вызывает `mcp__harness77__lint`), `shutdown` (C3: как клиент завершает stdio-сервер,
  на заглушке `stub_server77.py`), `registered` (C4: сервер, добавленный владельцем
  через `claude mcp add`, без конфигурации пробы; агент делает `lint`, `form-extract`
  и `build` по путям от каталога проекта).
- `claude_esc77.py` — C5: интерактивный Claude Code в псевдоконсоли (`pywinpty`) с тем же
  сервером; агент вызывает `run`, после начала расчёта проба нажимает Esc, затем просит
  `lint` и выходит через `/exit`. Экран — `C5-screen.txt`.
- `long_module77.1s` — модуль контракта этапа 4, контрольная функция которого занята
  150 с (пробы отмены N2, N3).

SDK не входит в зависимости продукта. Окружение пробы:

```powershell
python -m venv .local/mcp-client/venv
.local/mcp-client/venv/Scripts/python -m pip install "mcp==2.3.0" "pywinpty==3.1.0"
.local/mcp-client/venv/Scripts/python -B research/mcp/verify_mcp77.py conformance --output .artifacts/mcp/c1-NEW
python -B research/mcp/claude_probe77.py lint --output .artifacts/mcp/claude-NEW
claude.cmd mcp add harness77 -- python -m harness77 mcp   # один раз, из каталога проекта
python -B research/mcp/claude_probe77.py registered --output .artifacts/mcp/claude-c4-NEW
.local/mcp-client/venv/Scripts/python -B research/mcp/claude_esc77.py --output .artifacts/mcp/claude-c5-NEW `
  --project .local/stage14-native/project-long.toml --stand .local/stage14-native/stand.toml --run-id <UUID>
```

В Windows PowerShell `claude` — это `claude.ps1`, и PowerShell не передаёт ему `--`:
`claude mcp add harness77 -- python …` даёт `unknown option '-m'`. Поэтому `claude.cmd`.

Сервер и CLI запускаются интерпретатором с установленным harness77 (`--python`,
по умолчанию — базовый интерпретатор окружения пробы). Профили нативных проб —
`.local/stage14-native` (стенд этапа 4, шаблон `FIO.ERT`, база `base-for-test`).
