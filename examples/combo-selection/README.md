# Выбор COMBOBOX: задача 105

Технически проверено 16 ноября 2026 года: 12 основных нативных запусков
и три дополнительных, все с ожидаемыми исходами.
[Отчёт и свидетельства](../../docs/tasks/105-combo-selection-acceptance.md).

`select` выбирает единственный пункт по точному тексту. Пример на штатном
`СписокТиповУслуг` документа «Оказание услуг»: текущий пункт (без уведомления),
смена на «Оказание посредн. услуг в торговле», запись, закрытие и reopen.
Независимый reader ожидает сохранённый ТипУслуги=2, две прежние строки и итог 80.
Контролируемая ошибка в обработчике оставляет ТипУслуги=1; UI и reader должны
её обнаружить после записи. Четыре файла теста неизменны во всех фазах.

`prepare.py` принимает те же явные пути стенда, что пример services-project,
и обязательный `--sha256` wheel версии 0.12.0. Создаёт отдельный проект с
локальным launcher и harness77.txt. `run.py --output <новый каталог>` запускается
Python из acquisition.json без PYTHONPATH/PYTHONHOME; проверяет 12 исходов
baseline/regression/fixed/repeat-fixed через run, CLI suite и stdio MCP,
JSON/JUnit, MD-потоки, снимки входов, сохранность источника, реестра и процессов.

Пример шага JSON (также допустим в inline `steps` профиля):

```json
{"select": "СписокТиповУслуг", "text": "Оказание посредн. услуг в торговле"}
```

Параметры подготовки на квалифицированном локальном стенде; output должен
отсутствовать. При переносе задайте собственные пути и имя пользователя:

```powershell
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONIOENCODING = 'utf-8'
& .artifacts/s105-package/venv/Scripts/python.exe -B examples/combo-selection/prepare.py --base .local/bases/base-for-test --copy-path .local/bases/harness77-copy --exe 'C:/Program Files (x86)/1Cv77/BIN/1cv7l.exe' --cdb 'C:/Program Files (x86)/Windows Kits/10/Debuggers/x86/cdb.exe' --helper .artifacts/s104-inputs/helper.dll --identity .artifacts/s104-inputs/identity.dll --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT --controller research/forms/probe_module77.1s --wheel .artifacts/s105-package/dist/harness77-0.12.0-py3-none-any.whl --sha256 e883ed7d269a105c9006688c335a16835dbd50d2a358fd79bc6960c435b87a16 --installer-python (Get-Command python).Source --user ВВВ --copy-exclude ExtForms --copy-exclude actofsverok --copy-exclude temp --open-timeout-s 600 --calculation-timeout-s 300 --shutdown-timeout-s 60 --total-timeout-s 1500 --output .artifacts/s105-new-project
$python105 = (Get-Content .artifacts/s105-new-project/acquisition.json -Raw | ConvertFrom-Json).python
& $python105 -B .artifacts/s105-new-project/run.py --output .artifacts/s105-new-cycle
& $python105 -B .artifacts/s105-new-project/verify.py .artifacts/s105-new-cycle
& $python105 -B .artifacts/s105-new-project/controls.py --project .artifacts/s105-new-project --cycle .artifacts/s105-new-cycle --output .artifacts/s105-new-controls
```

`verify.py` повторно читает все 12 результатов, сравнивает диагностику между
транспортами и побайтно проверяет 48 снимков входов. Дополнительно сверяет
24 состояния геометрии и 216 отрицательных подмен измерений из задачи 104.
`controls.py` отдельно проверяет отсутствующий и дублирующийся пункт без
изменения сохранённых данных, затем модальное окно формулы выбора.

Поставка локальная, 0.12.0 ещё не опубликована. При новой сборке передавайте
её собственный проверенный SHA-256. Данные базы, DLL и компоненты стенда
в пример не входят. [Контракт](../../docs/tasks/105-combo-selection.md).
