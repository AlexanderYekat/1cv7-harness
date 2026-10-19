# Продолжение после задачи 012 (этап 5.1, поля ссылочных типов)

Задача 012: [задание](../tasks/012-reference-fields.md),
[приёмка](../tasks/012-reference-fields-acceptance.md). HEAD перед работой — `bb47e4e`,
ветка `master`. Задача принята по записанным ожиданиям (первый R1 опровергнут,
способ изменён до повтора); не закоммичено — коммит по слову владельца.

## Что появилось

- Продукт: `src/harness77/metadata77.py` — имена объектов `1Cv7.MD` и копии
  метаданных ERT; `form77.py` — схема 3 (`reference`), новые ссылочные `BMASKED`,
  `ert_metadata_action`; `artifacts.py` — `build --metadata`, замена копии
  метаданных ERT; `form-extract --metadata`; `run77.py` — метаданные стенда,
  `metadata_mismatch`; `config77.py` — `[build] metadata`.
- `research/forms/`: `repr:` → `representations` в `form_launcher77.py`;
  `references_module77.1s`, `prepare_references77.py`, `verify_references77.py`;
  `verify_corpus77.py --metadata`.
- Тесты: `tests/test_metadata77.py`, `tests/test_form77_references.py`,
  правка `tests/test_form77.py` (тип `B` теперь `reference`); адаптер формы (+1).
- `scripts/verify_package77.py --command-timeout-s` (по умолчанию 300 с): на
  нагруженной машине тесты установленного пакета шли 398 с.
- Документы: задание и приёмка 012, контракт описания формы и `run`, дорожная
  карта, README, README исследования, `docs/testing.md`.
- Локально: `.local/stage12-native/series` (R1–R5, эталоны `baselines/`,
  `fio-copy.ert`), `series-r1` (первый R1), `series-r1a` (R1a и пробы по одному
  полю), `series-r1b` (R1b, R1c).

## Воспроизведение

```powershell
python -B -m unittest discover -s tests
python -B -m unittest discover -s research/forms/tests
python -B research/forms/verify_corpus77.py .local/bases/base-for-test/ExtForms --output .artifacts/forms/corpus-NEW
python -B research/forms/verify_corpus77.py .local/bases/base-for-test/ExtForms `
  --metadata .local/bases/base-for-test/1Cv7.MD --output .artifacts/forms/corpus-md-NEW
python -m harness77 run --project .local/stage12-native/series/r-references.toml `
  --stand .local/stage12-native/series/stand.toml --output-root .artifacts/runs
python -B research/forms/verify_references77.py --runs .artifacts/runs --series .local/stage12-native/series `
  --corpus .artifacts/forms/corpus-20261019-v3 --corpus-md .artifacts/forms/corpus-20261019-v3-md `
  --output .artifacts/forms/references-acceptance-NEW.json
```

## Открыто

- Ручная проверка владельцем выполнена: в
  `.artifacts/runs/a4e4af88-a837-45b6-b3aa-5d934bb2af68/build/references-r-references.ert`
  выбор «…»/F4 в поле «Контрагент77» отработал, как ожидалось; «Документ77»
  («любой документ») сначала предлагает вид документа — так 1С выбирает значение
  неопределённого вида. Поле `Документ.Выписка` нативно не проверялось.
- Владелец открыл ERT с формой и копией R1 (модуль `references_foreign77.1s`, без
  обращения к данным) в «Торговля+Склад 9.2»: вид «Контрагенты» нашёлся по имени
  (там номер 172, а не 133), отсутствующий `Перечисление.Пол` превратил поле в
  строковое без ошибки. Следующая задача — 013 (дорожная карта): заменить
  `metadata_mismatch` и отказ при другом номере сверкой по именам — виды формы
  должны быть в базе.
- Эталоны `references-open` и `references-clicked` утвердил исполнитель после
  просмотра: `.local/stage12-native/series/baselines/*.png`.
- Замена копии метаданных кладёт в ERT полные метаданные базы (378 КБ); как такую
  ERT откроет Конфигуратор, не проверялось.
- Не входят: ссылочные `1CEDIT`, изменение типа существующих полей.
