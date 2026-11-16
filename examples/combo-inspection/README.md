# Чтение COMBOBOX: задача 106

Принято владельцем 16 ноября 2026 года: все 30 запусков примера и две
проверки совместимости 104–105 дали ожидаемые исходы.
[Отчёт и свидетельства](../../docs/tasks/106-inspect-combo-acceptance.md).

`inspect_combo` читает фактические пункты без изменения выбора и фокуса.
Подготовка требует тех же явных путей, что combo-selection, wheel 0.13.0
и его SHA-256. Используйте Python из acquisition.json без PYTHONPATH/PYTHONHOME.
`run.py --output <новый каталог>` сначала исследует два COMBOBOX, проверяет
счётчик обработчика и граничные состояния через run/CLI suite/MCP, затем
составляет шаги select из прочитанных строк и выполняет полный цикл 105
с дополнительными снимками. Прикладные fixture/reader взяты из принятой 105.

```json
{"inspect_combo": "СписокТиповУслуг"}
```

Результат находится в `form/combo-step-NNNN.json`: `items`, нулевой
`selected_index`, `selected_text`, `visible`, `enabled`. Нет выбора — индекс
и текст равны `null`; выбран пустой пункт — индекс числовой, текст `""`.
Порядок и дубликаты сохраняются. Ссылка с SHA-256 записана в шаге
`form-window.json` и в `run.json.result_files`. Схема артефакта — 1.

Пример начинает с двух шагов чтения без известных текстов. Первый успешный
запуск сохраняет `discovery.json` в созданном проекте; только после этого
генерируется `steps.json` для выбора, записи и reopen. Исходный пример
в репозитории сохраняет только начальные шаги исследования.

`run.py` проверяет шесть случаев через три транспорта: обычное чтение,
скрытый список с пустым строковым пунктом и дубликатами, пустой список,
отказ при 1001 пункте, успешный сценарий после отказа и контрольный select.
В каждом прикладном обработчике стоит счётчик с сообщением о каждом вызове.
При чтении сообщений нет; контрольный select публикует ровно вызов № 1.
Независимый reader проверяет сохранённый документ во всех случаях.

Затем `cycle.py` запускает baseline/regression/fixed/repeat-fixed через
run, CLI suite и stdio MCP. Ошибка в прикладном обработчике сохраняет
ТипУслуги=1 вместо 2: её должны обнаружить снимок после reopen и reader.
Четыре тестовых входа заморожены на все 12 запусков. `verify.py` повторно
проверяет этот цикл, хеши, диагностику, JSON/JUnit, геометрию с допуском 2 px
и отрицательные подмены измерений. Все 30 запусков входят в `run.py`.

Подготовка на квалифицированном локальном стенде (output должен отсутствовать):

```powershell
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONIOENCODING = 'utf-8'
& .artifacts/s106-package/venv/Scripts/python.exe -B examples/combo-inspection/prepare.py --base .local/bases/base-for-test --copy-path .local/bases/harness77-copy --exe 'C:/Program Files (x86)/1Cv77/BIN/1cv7l.exe' --cdb 'C:/Program Files (x86)/Windows Kits/10/Debuggers/x86/cdb.exe' --helper .artifacts/s104-inputs/helper.dll --identity .artifacts/s104-inputs/identity.dll --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT --controller research/forms/probe_module77.1s --wheel .artifacts/s106-package/dist/harness77-0.13.0-py3-none-any.whl --sha256 ef2d947f2e7887ac22caeaeedbc79a75d8754ee33d89b5a93b9e3dd263a56306 --installer-python (Get-Command python).Source --user ВВВ --copy-exclude ExtForms --copy-exclude actofsverok --copy-exclude temp --open-timeout-s 600 --calculation-timeout-s 300 --shutdown-timeout-s 60 --total-timeout-s 1500 --output .artifacts/s106-new-project
$python106 = (Get-Content .artifacts/s106-new-project/acquisition.json -Raw | ConvertFrom-Json).python
& $python106 -B .artifacts/s106-new-project/run.py --output .artifacts/s106-new-cycle
& $python106 -B .artifacts/s106-new-project/verify.py .artifacts/s106-new-cycle/cycle
& $python106 -B .artifacts/s106-new-project/verify_reads.py .artifacts/s106-new-cycle
```

При новой сборке передайте её проверенный SHA-256. Эта поставка локальная;
база, DLL и компоненты стенда в пример не входят. `enabled` означает
фактическое native-состояние окна, а не значение свойства формы 1С.
Недоступные окна отдельно проверены на уровне контракта runtime.
[Охват и критерии](../../docs/tasks/106-inspect-combo.md).
