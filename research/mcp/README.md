# Пробы MCP-сервера

## Клиенты и жизненный цикл MCP

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

## Восстановление открытой копии после падения suite

`verify_suite_recovery77.py` воспроизводит [задачу 081](../../docs/tasks/081-mcp-suite-open-copy-after-partial-crash.md).
Для прогона нужны Windows, установленный `harness77` и свободный нативный стенд
1С 7.7.027. TOML стенда задаёт исходную базу, платформу, x86 CDB, обе DLL и
закреплённые версии и хеши. TOML проекта задаёт модули конфигурации и один
тест `execute` со статусом `passed` и ожидаемым значением `42`. Если
`expect_value` отсутствует, проба подставляет `42`. Профиль проекта должен
запускаться без визуальных проверок и с `keep_copy = false`.

Команда для локального стенда из корня репозитория

```powershell
python -B research/mcp/verify_suite_recovery77.py --stand .local/stage21-native/stand.toml --project .local/stage21-native/s3/cases/m-same/project.toml --output .artifacts/s82-native
```

Относительные пути внутри профилей разрешаются от каждого TOML. Для каждого
прогона указывайте новый каталог результатов с ASCII-путём без пробелов,
кавычек и точки с запятой. Проба записывает туда производные TOML, временно
регистрирует `<output>/copy` в списке баз текущего пользователя и использует
launcher из репозитория.

Проба завершает собственные MCP, CLI и launcher после проверки их
принадлежности к прогону. CDB, 1С и OLE-клиент выходят штатно после снятия
паузы. Результаты и проверка очистки сохраняются в `<output>/verified.json`,
отчёт набора и JUnit — в `<output>/crash`.
[Подробности задачи 082](../../docs/tasks/082-native-suite-recovery-probe.md).

Для [задачи 083](../../docs/tasks/083-native-suite-concurrent-recovery.md)
укажите `--retries 2`. Два отдельных MCP-сервера отправляют по запросу
`run` на один `copy_path`. В `verified.json` массив `retries` идёт в
порядке получения копии. Для каждого запроса записываются значение теста,
число вызовов `Initialize`, время ожидания пути и снятые старые
COM-регистрации.

Для [задачи 084](../../docs/tasks/084-native-suite-recovery-cancel-waiter.md)
добавьте `--cancel-waiter` к `--retries 2`. Проба отправляет второй запрос,
когда первый уже держит восстановленную копию, и отменяет его в очереди
через `notifications/cancelled`. В `verified.json` запись
`cancelled_retry` описывает отмену, а массив `retries` содержит успешные
запуски владельца и нового запроса.

Тот же режим удержания владельца используется для следующих проверок
(все флаги требуют `--retries 2` и взаимно исключают друг друга):

- [085](../../docs/tasks/085-native-suite-recovery-timeout-waiter.md):
  `--timeout-waiter` задаёт ожидающему запросу `open_timeout_s=25`.
  Запись `timed_out_retry` подтверждает отказ до захвата замка и старта 1С;
  MCP возвращает ошибку и продолжает отвечать на `ping`.
- [086](../../docs/tasks/086-native-suite-recovery-close-waiter.md):
  `--close-waiter` закрывает stdin ожидающего MCP. Запись `closed_retry`
  подтверждает отмену CLI и доставку ответа перед штатным выходом MCP.
- [087](../../docs/tasks/087-native-suite-recovery-crash-waiter.md):
  `--crash-waiter` завершает собственные ожидающие MCP и CLI после проверки
  их образов, времени создания и родительских PID. Запись `crashed_retry`
  сохраняет идентичности завершённых процессов; итогового `run.json` и
  ответа MCP у прерванного запроса быть не должно.

Во всех трёх режимах проба сверяет копию, замок, COM-регистрации и живые
процессы владельца до его освобождения. Массив `retries` содержит успехи
владельца и нового запроса на том же пути: значение `42` и один `Initialize`
у каждого. Прерванный suite остаётся с `complete=false`, первый дочерний
результат и JUnit сохраняются. Итоговая `cleanup` проверяет исходную базу,
список баз, COM, процессы и удаление временной копии с замком.
