# Продолжение после задачи 005 (этап 5)

Задача 005 выполнена: [задание](../tasks/005-kudir-rules.md),
[приёмка](../tasks/005-kudir-rules-acceptance.md). HEAD перед работой — `55b68ef`,
ветка `stage4-full-cycle`. Изменение `research/kudir/README.md` в рабочем дереве —
работа владельца, в задачу не входит и не трогалось.

## Что появилось

- `src/harness77/catalog77.py` и команда `harness77 catalog`; пакетные
  `catalog77.json` (7.70.027) и `lint77-globals.json` (35 глобальных имён стенда).
- `lint77` 0.2.0: L7708–L7711, контекст формы (`Source.dialog`, `--dialog`),
  поля отчёта `catalog` и `form_context_modules`. `run77` передаёт статике диалог
  шаблона сборки.
- `research/rules77/` — исполнитель нативных проб и экспорт глобальных имён;
  `scripts/verify_kudir_rules77.py` — сверка с пробами и корпусом КУДиР.
- Тесты `test_catalog77`, `test_lint77_rules`; `verify_package77.py` проверяет
  оба новых ресурса.

## Воспроизведение

```powershell
python -m pip install --no-build-isolation -e .
python -B -m unittest discover -s tests
python scripts/verify_package77.py
python scripts/verify_kudir_rules77.py --corpus research/kudir/corpus `
  --evidence .artifacts/stage5-rule-probes-20261015.json `
  --evidence .artifacts/stage5-rule-probes-20261015-rerun.json `
  --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT `
  --output .artifacts/stage5-acceptance-<дата>.json
```

Повтор нативных проб — [research/rules77](../../research/rules77/README.md).
Каталог при смене платформы: `harness77 catalog --als … --strings … --output …`;
тест `test_packaged_catalog_matches_installed_platform` сравнит его с пакетным.

## Что важно знать

- Пробы опровергли часть исходных гипотез КУДиР: объявлять нельзя только 162
  имени зарезервированного блока (`Сообщить` можно), лишний аргумент падает
  не у всех объектов, длинную строку отвергает Конфигуратор, а не компилятор.
- `lint77-globals.json` снят на бухгалтерской конфигурации стенда. При другой
  конфигурации повторить `u-survey` или передавать имена через `--allow`.
- Одна проба первой серии заблокирована сроком готовности отладчика (CDB) —
  известный инфраструктурный отказ ядра platform77, не исход конструкции.

## Следующий шаг

Выбор владельца (см. [дорожную карту](../roadmap.md)): долгий нативный отчёт КУДиР
через `run`, разметка корня/каскада протокола по каталогу сообщений `1crcrus.dll`
или формы (5.1).
