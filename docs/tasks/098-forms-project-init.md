# Задача 098. Прикладной forms-проект через project-init

Дата — 13 ноября 2026 года. Продолжение принятых 094 и 097.
Реализована и проверена 13 ноября 2026 года.
Задача принята владельцем 13 ноября 2026 года.

## Ожидания до нативного запуска

Новый wheel 0.6.0 должен создавать прикладной проект одной командой:
`project-init --runtime forms --source module.1s --scenario scenario.json`
с прежними обязательными directory/id/template и пятью сроками.
Входной JSON задаёт parameters/tests; прикладные правила остаются во входах.
Проект сразу содержит schema_version=2, UI-сценарий, fixture reader,
expect_json и подписи. Ручная замена профиля и модуля после создания исключена.
Побайтные module.1s/template.ert/scenario.json и относительные пути
позволяют переносить каталог. configuration/ создаётся пустой.
Прежний headless-вызов совместим. Инициализация не запускает 1С и не выбирает стенд.

Сохраняются проверки и атомарная публикация 094 без перезаписи, включая
позднюю гонку с пустым каталогом. Все входы перечитываются до публикации,
результат содержит хеши/размеры. Ошибочные аргументы/сценарии/модули
дают blocked/2 без частичного проекта.

Из нового venv без pip, с единственным установленным harness77, из другого
CWD и без PYTHONPATH/PYTHONHOME создать семь прикладных проектов по входам
097. Не менять созданные профили/ERT/сценарии; прикладной модуль проведения
подготовить через md-extract в configuration/. Один контролируемый дефект
суммы проводки должен давать те же две JSON-диагностики, что в 096–097.

Прямые run: baseline/regression/fixed → passed/failed/passed. Затем
неизменные проекты через CLI suite и stdio MCP suite:
baseline/regression/fixed/repeat-fixed → passed/failed/passed/passed,
invalid-json/empty-json/recovered → blocked/blocked/passed.
Проверить JUnit failure/error, isError, ping и следующий успешный suite.
Независимо перечитать созданные проекты, raw протоколы/JSON, отчёты,
SHA-256, плановые MD и все их потоки, один Initialize и штатную очистку.
Источник, реестр, входы/runtime и чужие процессы должны сохраниться.
Охват ограничен документом «Готовая продукция» и стендом Windows/7.70.027.

## Воспроизведение

[Самостоятельный пример и команды](../../examples/forms-project-init/README.md).

```powershell
python -B scripts/verify_package77.py --output .artifacts/s98-package --command-timeout-s 600
```

## Результаты

- `.artifacts/s98-package/summary.json`: passed. Wheel 0.6.0 собран из
  sdist, офлайн установлен в новый venv без pip; из другого CWD, без
  PYTHONPATH/PYTHONHOME выполнены 595 тестов: 590 успешных и пять пропусков
  (четыре ограничения Windows symlink и одна проверка другого OS).
- Четыре новых теста создания forms проверяют точные байты входов,
  структурированные ожидания, ошибки/неоднозначности JSON и модуля,
  сочетания аргументов, изменение входов до публикации и CLI text/json.
  Ещё один тест запускает созданные проекты без редактирования через
  настоящие процессы run/suite/MCP на simulation, с контролируемым провалом.

## Нативная проверка из чистого wheel

[Полная серия](../../.artifacts/s98-native/verified.json) — passed.
Использован отдельный venv с единственным установленным harness77;
дочерние CLI, MCP и launcher импортируют пакет из него. CWD находится
в отдельном working, PYTHONPATH/PYTHONHOME отсутствуют. Все 36 файлов ядра
совпадают с checkout; 33 нативных файла совпадают с принятой 097.

Семь проектов созданы project-init, включая каталог с кириллицей и пробелами.
Каждый прошёл doctor ready/0 без запуска 1С. Профили, module.1s,
template.ert и scenario.json после инициализации сохранены побайтно;
сценарии/JSON-ожидания независимо сверены с входами. Через md-extract
подготовлен только модуль проведения внутри configuration/.

Семь отказов (существующие проект/пустой каталог, неправильные JSON-ожидания,
непредставимый модуль, отсутствующий source, несовместимый runtime,
недостаточный total) дали blocked/2, platform_checked=false,
launch_performed=false. Существующие проекты/каталоги сохранены,
частичных проектов и временных каталогов нет.

- Прямые run baseline/regression/fixed: **passed/failed/passed**, коды 0/1/0.
  Регрессия меняет единственную строку прикладного модуля, оставляя тесты
  неизменными. Reader получает суммы 10/20 вместо 30/40; исправление проходит.
- [CLI regression](../../.artifacts/s98-native/cli-regression/suite/suite.json)
  и [MCP regression](../../.artifacts/s98-native/mcp-regression/suite/suite.json):
  **passed/failed/passed/passed**, итог failed/1, counts 3/1/0/0,
  по одному JUnit failure. MCP возвращает **isError=false**.
- [CLI invalid-results](../../.artifacts/s98-native/cli-invalid-results/suite/suite.json)
  и [MCP invalid-results](../../.artifacts/s98-native/mcp-invalid-results/suite/suite.json):
  **blocked/blocked/passed**, итог blocked/2, counts 1/0/2/0,
  по два JUnit error: json_result_invalid и json_result_missing.
  MCP возвращает **isError=true**.
- Тот же MCP PID 12984 после blocked выполнил
  [успешный новый suite](../../.artifacts/s98-native/mcp-success/suite/suite.json),
  passed/0, isError=false; сервер завершился с кодом 0.
  Все три запроса имеют правильный progressToken, возрастающий прогресс
  и границы сценариев; ping успешен во время и после запросов.
  [Полный трафик](../../.artifacts/s98-native/mcp-traffic.json).

Во всех провалах ровно два расхождения: `/entries/0/amount` и
`/entries/1/amount`, подписи «Проводка 1, сумма»/«Проводка 2, сумма»,
строковые типы, значения 30→10 и 40→20. Сохранённый документ, строки,
количества и прочие тесты корректны. Диагностика совпадает в run,
suite.problems и JUnit; нормализованные результаты CLI/MCP равны.

Всего **18 нативных запусков**, без пропусков и автоматических повторов.
В каждом подтверждены владение, один Initialize, успешные нативные операции,
штатная очистка без forced_cleanup, удаление копии и освобождение замка.
Сверены **3598 потоков каждой из семи плановых MD**: только регрессионная
меняет единственный поток модуля проведения. Источник, MD/DD/DLL, реестр,
guard, kit и установленный runtime сохранены. Чужой PID 18812 сохранил
parent=7676, образ и creation_filetime=134390187986538342 во всех запусках.

## Независимая сверка и артефакты

[Повторное чтение](../../.artifacts/s98-reread.json) независимо подтвердило
семь проектов, три прямых запуска и пять наборов (ещё 15 запусков).
[Контроли проектов](../../.artifacts/s98-project-controls/controls.json)
отклонили **15 подмен**: байты четырёх файлов, согласованно пересчитанные
хеши, относительный source, подписи, сроки, runtime/launch/platform,
входной хеш, размер и ID случая. Дополнительно проверены все плановые MD,
установленные файлы, происхождение 18 launcher и текущее состояние стенда.

[Контроли suite](../../.artifacts/s98-suite-controls/controls.json) отклонили
**33 подмены** run/suite/JUnit/raw JSON/UI, включая шесть согласованных
изменений диагностики с пересчитанными хешами. Для отрицательных JSON-случаев
дополнительно проверены все raw UI-протоколы прежним verifier 033; допускается
только известное ему расхождение агрегатного статуса blocked вместо failed.
Оригиналы после контролей повторно перечитаны и сохранены.

```powershell
.artifacts/s98-kit/venv/Scripts/python.exe -B scripts/verify_forms_project77.py --kit .artifacts/s98-kit --native .artifacts/s98-native --output .artifacts/s98-project-controls
```

Выберите новый output для повтора. Общая сверка:
[s98-evidence.json](../../.artifacts/s98-evidence.json).

Wheel: [harness77-0.6.0](../../.artifacts/s98-package/dist/harness77-0.6.0-py3-none-any.whl).
SHA-256: `221991f09dec4ab0bd3d07912d6a46904574835d275fd14665c79c400ad74d2a`.
[Самостоятельный комплект](../../.artifacts/s98-kit.zip) содержит 16 файлов
и kit.json, без venv, базы и готовой MD; архив перечитан и хеши сверены.
SHA-256: `c563f896b32081aa0efd3716e3e74a67b302cdf6623bad47e28c6fd90e091b8d`.
Документация внутри дистрибутивов отражает момент сборки; итог 098 — здесь.

Произвольные документы, версии платформы, UI-семантика нового сценария,
отмена и падение сервера этой серией повторно не квалифицируются.
