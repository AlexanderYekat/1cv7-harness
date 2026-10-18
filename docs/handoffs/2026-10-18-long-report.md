# Продолжение после задачи 006 (этап 5)

Задача 006 принята: [задание](../tasks/006-long-native-report.md),
[приёмка](../tasks/006-long-native-report-acceptance.md). HEAD перед работой — `15ef169`,
ветка `stage4-full-cycle`. Проект КУДиР не менялся.

## Что появилось

- `research/platform77/session77.py`: `client_timeout_seconds` (по умолчанию 140)
  и `cancel_path`; `stage4_launcher77.py`: адаптер, `preflight_copy`, фазы 8.5.
- `research/kudir/`: `kudir_launcher77.py` (адаптер КУДиР), `cancel_run77.py`
  (Ctrl+Break по таймеру), `snapshot_state77.py`, `verify_long_report77.py`, тесты.
- Продукт: `[platform.parameters]`, команды тестов в launcher, своя группа процессов,
  Ctrl+Break, правило неполных файлов по операции, потоковое свидетельство.
- Локальные профили — `.local/stage6-native/` (база на D:, пути машины).

## Воспроизведение

```powershell
python -B -m unittest discover -s tests
python -B -m unittest discover -s research/platform77/tests
python -B -m unittest discover -s research/kudir/tests
python -m harness77 run --project .local/stage6-native/project-full.toml `
  --stand .local/stage6-native/stand-kudir-d.toml --output-root .artifacts/runs
```

Проверка всех прогонов — `research/kudir/verify_long_report77.py` (пример вызова
в его docstring; роли и run_id — в приёмке и `.artifacts/stage6-acceptance-20261018-final.json`).

## Открыто

- Ручной Ctrl+C владельца (N5b) выполнен и принят. После принудительной
  остановки 1С при следующем открытии штатно переиндексирует базу (данные
  не меняются).
- Часовой расчёт не проверялся; мягкого прерывания выгрузки нет (только остановка
  своей 1С).
- Следующий шаг этапа 5 — выбор владельца: разметка корня и каскада протокола
  или формы (5.1).
