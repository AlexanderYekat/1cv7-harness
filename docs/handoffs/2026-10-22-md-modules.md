# Продолжение после задачи 021 (модули 1Cv7.MD на копии базы)

Задача 021: [задание](../tasks/021-md-modules.md), [приёмка](../tasks/021-md-modules-acceptance.md).
HEAD перед работой — `9a86c96`, ветка `master`. Предыдущая передача — [020](2026-10-22-md-module-context.md).
Задачу принял владелец 22 октября; коммит — сразу в `master` и на GitHub (как в 016–020).

## Что появилось

- `harness77 md-extract` / `md-build` (`src/harness77/md77.py`, MCP — те же инструменты): модули
  `1Cv7.MD` по файлам с именами объектов и обратно, только изменённые модули, индекс `modules.json`.
- `metadata77.Metadata.module_object()` — объект и форма папки модуля.
- `src/harness77/basecopy77.py` — копия базы по `copy_path` (замок, метка, исключения, удаление,
  перечень источника, журнал сеанса).
- `run`: `[configuration]` проекта, `copy_path`/`copy_exclude` стенда, этап `configuration`,
  статика только новых замечаний изменённых модулей, `base_copy`, `configuration_diagnostics`,
  `configuration_compilation_failed`.
- Launcher: `--configuration-sha256`, `built_copy` (метка этого прогона и регистрация пути),
  `pinned_for`; ядро: `pinned` у `run_session`/`assess`, `open.timeout_windows`, `base_list`.
- `research/md/probe_md77.py`, `scripts/verify_md77.py`; тесты `test_md77`, `test_run77_configuration`.

## Стенд

- В список баз 1С владельца добавлено значение `HKCU\Software\1C\1Cv7\7.7\Titles`:
  `C:\MyProjects\harness77\.local\bases\harness77-copy\` = «harness77 — копия базы» (разрешение
  владельца 22 октября). Каталога копии между прогонами нет — его создаёт и удаляет `run`.
- Локальный профиль стенда задачи — `.local/stage21-native/stand.toml` (профиль `stage14` +
  `copy_path` и `copy_exclude`); `stand-shots.toml` — то же со снимками.

## Воспроизведение

Тесты — как в [testing.md](../testing.md). Нативно — команды в
[README исследования](../../research/md/README.md), свод и корпус — шапка `scripts/verify_md77.py`.
Свидетельства: `.artifacts/stage21-md-probes-20261022-*.json`, `.artifacts/stage21-acceptance-20261022.json`,
`.artifacts/package77-stage21-20261022`.

## Открыто

- Проверка владельца (по желанию): `keep_copy = true`, копия в Конфигураторе, синтаксический контроль.
- Имена в сообщениях 1С для форм справочников, журналов, отчётов и обработок нативно не проверены
  (привязка к изменённому объекту по имени, без файла).
- Изредка 1С под отладчиком не доходит до `CoRegisterClassObject` за срок открытия (2 из 31 прогона
  проб), до открытия базы — причина не выяснена.
- Возможное продолжение: новые модули и формы внутри `1Cv7.MD` (раздел 5.1), изменение метаданных,
  данные тестов на копии (копия уже свежая на каждый прогон — тесты, меняющие данные, воспроизводимы).
