# Самостоятельный проект счёта-фактуры (100)

## Прямое открытие и переоткрытие (101, wheel 0.8.0)

Для нового прямого сценария добавьте `--direct --wheel <wheel-0.8.0>`.
Bootstrap Python должен содержать новую установленную поставку. В проект
включается выбранный wheel с закреплением версии/SHA-256; опубликованный
0.7.0 не подменяется и не объявляется поддерживающим новую возможность.

Для получения опубликованного 0.8.0 в команде ниже замените `--wheel …` на
`--url https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.8.0/harness77-0.8.0-py3-none-any.whl --version 0.8.0 --sha256 <SHA-256 из SHA256SUMS.txt релиза>`
и выберите новый output, например `C:/MyProjects/h77-101-published`.
Версия, URL и хеш передаются вместе; сочетание с локальным --wheel запрещено.
В новом проекте нет bundled wheel или кеша: `.harness77/launch.py prepare`
скачивает закреплённый asset, проверяет SHA-256 и устанавливает его изолированно.
Последующие run/suite/MCP используют ту же проверенную поставку. Файл
`acquisition.json` сохраняет source, версию, хеш и путь Python.

```powershell
python -B examples/invoice-project/prepare.py --direct --wheel C:/MyProjects/harness77/.artifacts/s101-package/dist/harness77-0.8.0-py3-none-any.whl --installed-python C:/MyProjects/harness77/.artifacts/s101-package/venv/Scripts/python.exe --base C:/MyProjects/harness77/.local/bases/base-for-test --copy-path C:/MyProjects/harness77/.local/bases/harness77-copy --exe 'C:/Program Files (x86)/1Cv77/BIN/1cv7l.exe' --cdb 'C:/Program Files (x86)/Windows Kits/10/Debuggers/x86/cdb.exe' --helper C:/MyProjects/harness77/.artifacts/s99-kit-final/dependencies/helper.dll --identity C:/MyProjects/harness77/.artifacts/s99-kit-final/dependencies/identity.dll --template C:/MyProjects/harness77/.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT --controller C:/MyProjects/harness77/research/forms/probe_module77.1s --user ВВВ --copy-exclude ExtForms --copy-exclude actofsverok --copy-exclude temp --output C:/MyProjects/h77-101-direct
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONIOENCODING = 'utf-8'
$state = Get-Content C:/MyProjects/h77-101-direct/acquisition.json -Raw | ConvertFrom-Json
& $state.python -B C:/MyProjects/h77-101-direct/run.py --output C:/MyProjects/h77-101-cycle
& $state.python -B C:/MyProjects/h77-101-direct/verify.py C:/MyProjects/h77-101-cycle
```

Тесты 101 — direct-fixture.1s, direct-reader.1s и direct-steps.json; при
создании они копируются в обычные fixture/reader/steps проекта. Fixture
возвращает непосредственно сохранённую фактуру; reader читает её по этой
ссылке. Основание и журнал не создаются. В parameters явно заданы
`fixture_mode="existing"`, `caption_control="кнПечать"`, `caption_text="Печать"`.
При reopen та же подпись задана явно; проверки читают текст кнопки до правки
и после повторного открытия. UI сохраняет и проверяет те же суммы 90/140.

Четыре фазы идут через run, CLI suite и MCP suite с одинаковыми тестами;
отдельные отрицательные контроли неверной подписи первого открытия и reopen
должны дать failed. Это 12 запусков основного цикла и два контроля подписи.
Новый релиз автоматически не публикуется. Далее описан прежний режим 100,
который остаётся доступен без `--direct`.

## Открытие через журнал (100, опубликованный wheel 0.7.0)

Проект создаётся по явным входам, без комплектов 095–099. `prepare.py`
использует установленный harness77 только для project-init, stand-init и connect;
локальная команда затем сама скачивает опубликованный wheel 0.7.0 из GitHub
и проверяет SHA-256. Все проверки выполняются этой поставкой вне checkout.
Нужны Python >=3.11 с pip, Windows, квалифицированные 1С 7.70.027/DBF,
1С++/FormEx и компоненты helper/identity.

Передайте `prepare.py --installed-python ... --base ... --copy-path ... --exe ...
--cdb ... --helper ... --identity ... --template ... --controller ... --user ...
--copy-exclude ExtForms --copy-exclude actofsverok --copy-exclude temp --output ...`.
Все пути — явные входы; output должен отсутствовать. Controller — модуль ERT
для управления тестом, template — существующая ERT. Новая исходная база не создаётся.

Команда проверенного стенда (пути DLL являются явными файлами, kit.json не читается):

```powershell
python -B examples/invoice-project/prepare.py --installed-python C:/MyProjects/h77-099-kit/venv/Scripts/python.exe --base C:/MyProjects/harness77/.local/bases/base-for-test --copy-path C:/MyProjects/harness77/.local/bases/harness77-copy --exe 'C:/Program Files (x86)/1Cv77/BIN/1cv7l.exe' --cdb 'C:/Program Files (x86)/Windows Kits/10/Debuggers/x86/cdb.exe' --helper C:/MyProjects/harness77/.artifacts/s99-kit-final/dependencies/helper.dll --identity C:/MyProjects/harness77/.artifacts/s99-kit-final/dependencies/identity.dll --template C:/MyProjects/harness77/.local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT --controller C:/MyProjects/harness77/research/forms/probe_module77.1s --user ВВВ --copy-exclude ExtForms --copy-exclude actofsverok --copy-exclude temp --output C:/MyProjects/h77-100-application
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONIOENCODING = 'utf-8'
C:/MyProjects/h77-100-application/.harness77/cache/0.7.0-7f0f81e8ead500ba/venv/Scripts/python.exe -B C:/MyProjects/h77-100-application/run.py --output C:/MyProjects/h77-100-application-cycle
C:/MyProjects/h77-100-application/.harness77/cache/0.7.0-7f0f81e8ead500ba/venv/Scripts/python.exe -B C:/MyProjects/h77-100-application/verify.py C:/MyProjects/h77-100-application-cycle
```

Для повторного создания выбирайте новый output. При воспроизведении на другом
компьютере замените пути входов и пользователя. Из опубликованного wheel можно
подготовить первоначальное окружение обычными venv/pip; окружение из 099 здесь
служит только установленным bootstrap, а не источником прикладного проекта.

В `acquisition.json` сохранены результат скачивания, версия, хеш и Python
изолированного окружения. Этим Python запустите `-B <проект>/run.py --output <новый-каталог>`,
а затем `-B <проект>/verify.py <каталог-результатов>`.
`harness77.txt` включает локальную команду `.harness77/launch.py`;
AGENTS.md и настройки находятся только внутри этого проекта.

Fixture создаёт покупателя, договор, подразделение, товар, расходную накладную
и подчинённый счёт-фактуру с двумя строками 1×50 и 1×30. UI находит точную
накладную в журнале, открывает подчинённый документ по точной ссылке,
меняет количество второй строки на 3, записывает, закрывает и повторно
открывает ту же ссылку. Ожидание заранее
зафиксировано в expected.json: первая строка 50, вторая 90, итоги 140.
После закрытия формы reader открывает новый объект документа по точной ссылке и читает сохранённые
строки, связь с основанием, ссылки товаров, комментарий, признак проведения и итоги.

Открытие через подчинённый журнал использует поддержанный в wheel контракт
`caption_control/caption_text`: штатный модуль меняет «Печать...» на «Печать».
Прямое открытие этой формы в 0.7.0 даёт ложное расхождение подписи, а override
для прямого reopen не поддерживается. В рабочем сценарии задано точное
ожидание «Печать»; проверка подписей сохранена. Это ограничение инструмента,
а не ошибка расчёта документа.

Контролируемая ошибка добавляет 1 к пересчёту суммы в модуле штатной формы.
Получаются 91 и 141; UI и структурированная проверка должны дать failed.
Исправление восстанавливает исходный модуль побайтно. Четыре варианта
baseline/regression/fixed/repeat-fixed идут через run, CLI suite и живой stdio
MCP suite. Тесты во всех вариантах одинаковы. JSON/JUnit и raw JSON перечитываются
независимо; проверяются MD-потоки, сохранность источника, реестр, процессы
и очистка копии. Ожидаемый общий статус suite — failed из-за regression;
статус проверочного сценария — passed только после всей сверки.

Результаты, окружения и кеш не включайте в переносимый проект. Пути стенда
привязаны к компьютеру; источник базы остаётся внешним входом.
