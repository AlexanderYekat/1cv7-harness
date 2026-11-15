# Документ «Оказание услуг»: прикладной тест 104

Технически проверена 15 ноября 2026 года: все 12 ожидаемых исходов
через run/CLI suite/MCP, независимая сверка и сохранность стенда подтверждены.
[Задание](../../docs/tasks/104-services-project.md),
[свидетельства, исправление и ограничения](../../docs/tasks/104-services-project-acceptance.md).

Новый тест штатной формы `ОказаниеУслуг` на квалифицированной DBF-базе.
Fixture создаёт две строки 1×50 и 1×30 и нулевые ставки налогов.
UI меняет вторую строку на 3×30, записывает и переоткрывает ту же ссылку.
Независимый reader ожидает 50/90 и итог 140. Контролируемая ошибка `+1`
должна дать 50/91 и 141 без изменения тестов.

`prepare.py` запускается Python с установленным wheel выбранной версии
и принимает явные `--base`, `--copy-path`, `--exe`, `--cdb`,
`--helper`, `--identity`, `--template`, `--controller`, `--wheel`,
`--user`, `--output` и повторяемый `--copy-exclude`. Выход должен отсутствовать.
Если bootstrap установлен без pip, передайте `--installer-python` с путём
Python, в котором доступен `pip --python`.
Передайте `--sha256` из доверенной квалификации выбранного wheel.
Без этого аргумента используется прежний хеш опубликованной 0.10.0
(он подходит для воспроизведения исходного отказа, до исправления COMBOBOX).
Wheel сверяется с хешем и включается в проект.
Подготовка создаёт profile схемы 4 с четырьмя файловыми входами,
stand.toml, suite.toml и локальное подключение через harness77.txt.

После подготовки Python из `acquisition.json` запускает
`-B <проект>/run.py --output <новый-каталог>` из каталога вне checkout.
PYTHONPATH и PYTHONHOME должны быть сняты. Все операции выполняются
локальным launcher; исходная база не изменяется, run работает на копии.

Результаты включают исходный и изменённый модули, diff, плановые MD,
независимую проверку потоков, JSON/JUnit и свидетельства сохранности стенда.
Утилиты контейнерной сверки и транспорта переиспользованы из предыдущих
примеров; fixture, reader, шаги и ожидания относятся к услугам.

## Исправленная поставка 0.11.0

Локальный wheel: `.artifacts/s104-package-final/dist/harness77-0.11.0-py3-none-any.whl`,
SHA-256 `20bb2323ff379fe0a11cc6f20547b8c342a9dfad9d83517237d8a95cc7e052e6`.
Bootstrap: `.artifacts/s104-package-final/venv/Scripts/python.exe`.
Подготовленный проект: `.artifacts/s104-final-run-project`.
Полная серия: `.artifacts/s104-final-run`.

Команда квалифицированного стенда из корня репозитория (заменяйте пути
и пользователя при переносе; output должен быть новым):

```powershell
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONIOENCODING = 'utf-8'
$wheel104 = (Resolve-Path '.artifacts/s104-package-final/dist/harness77-0.11.0-py3-none-any.whl').Path
& .artifacts/s104-package-final/venv/Scripts/python.exe -B examples/services-project/prepare.py --base .local/bases/base-for-test --copy-path .local/bases/harness77-copy --exe 'C:/Program Files (x86)/1Cv77/BIN/1cv7l.exe' --cdb 'C:/Program Files (x86)/Windows Kits/10/Debuggers/x86/cdb.exe' --helper .artifacts/s104-inputs/helper.dll --identity .artifacts/s104-inputs/identity.dll --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT --controller research/forms/probe_module77.1s --wheel $wheel104 --sha256 20bb2323ff379fe0a11cc6f20547b8c342a9dfad9d83517237d8a95cc7e052e6 --installer-python (Get-Command python).Source --user ВВВ --copy-exclude ExtForms --copy-exclude actofsverok --copy-exclude temp --open-timeout-s 600 --calculation-timeout-s 300 --shutdown-timeout-s 60 --total-timeout-s 1500 --output .artifacts/s104-final-run-project
$python104 = (Get-Content .artifacts/s104-final-run-project/acquisition.json -Raw | ConvertFrom-Json).python
& $python104 -B .artifacts/s104-final-run-project/run.py --output .artifacts/s104-final-run
& $python104 -B .artifacts/s104-final-run-project/verify.py .artifacts/s104-final-run
```

DLL и контроллер задаются явными файлами, данные исходной базы в пример
не входят. Точный состав проверенной поставки записан в manifest внутри wheel.
`verify.py` независимо перечитывает отчёты 12 запусков, JSON/JUnit, снимки
входов, геометрию первого открытия/reopen и 216 отрицательных подмен геометрии.
