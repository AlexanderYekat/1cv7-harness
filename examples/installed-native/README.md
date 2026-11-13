# Штатный нативный исполнитель (092)

Начиная с 0.2.0 wheel harness77 содержит квалифицированные адаптеры headless и forms,
их Python/VBS/1С-файлы и манифест SHA-256. В профиле стенда выберите
`runtime = "forms"` или `runtime = "headless"` внутри `[stand]`.
`runtime` и прежний путь `launcher` взаимоисключающие; явный launcher
работает по прежнему контракту.

С 0.3.0 новый локальный профиль можно создать через
[`harness77 stand-init`](../stand-init/README.md) по явно выбранным путям.

Квалифицированы Windows, 1С 7.70.027 и x86 CDB с закреплёнными компонентами.
Штатный runtime требует `[configuration] modules` проекта и
`[stand.base] copy_path`, зарегистрированный в списке баз 1С. Пустой каталог
modules допускается: используется неизменённая конфигурация на свежей копии.
Пути платформы, CDB, helper/identity DLL, базы и хеши задаются профилем.
DLL и база остаются внешними зависимостями. Установка wheel не запускает
1С и не выполняет регистрацию COM.

Сборка и подготовка примера из checkout:

```powershell
python -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir .artifacts/s92-wheel .
python -B examples/installed-native/prepare.py --stand .local/stage21-native/stand.toml --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT --wheel .artifacts/s92-wheel/harness77-0.4.0-py3-none-any.whl --output C:/MyProjects/harness77/.artifacts/s92-kit
```

Пример содержит wheel, зависимости стенда, входы и профили сценария 033,
headless-проверку 42, контролируемое ожидание для отмены и независимую
проверку отчётов. Копии runtime и launcher.py в каталоге примера нет.

Исполнение после переноса комплекта, без checkout:

```powershell
$kit = 'C:/MyProjects/harness77/.artifacts/s92-kit'
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
python -m venv --without-pip "$kit/venv"
python -m pip --python "$kit/venv/Scripts/python.exe" install --no-index --no-deps "$kit/harness77-0.4.0-py3-none-any.whl"
& "$kit/venv/Scripts/python.exe" -B "$kit/run.py" --output C:/MyProjects/harness77/.artifacts/s92-result
```

Проверяющий скрипт выполняет doctor до/после запуска, два набора с
ожидаемыми кодами 0/1, headless и отмену через публичный cancel-file,
затем новый запрос. Временные копии принадлежат своим run_id.
Результаты, JUnit и очистка проверяются независимо; прежние отчёты не
перезаписываются. Для повторной проверки выберите новый output.

Проверка поставки и повреждений runtime описана в задаче 092 проекта.
