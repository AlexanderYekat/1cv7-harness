# Создание профиля из установленного пакета (093)

Команда `harness77 stand-init` включена в wheel 0.3.0. Она принимает явные
пути платформы, CDB, helper/identity DLL, базы и зарегистрированного пути
копии, режим forms/headless и пользователя с ранее разрешённым пустым
паролем. Проверяет квалификацию и сохраняет новый TOML с SHA-256.

```powershell
harness77 stand-init --output stand.toml --name local --runtime headless `
  --exe 'C:/Program Files (x86)/1Cv77/BIN/1cv7l.exe' `
  --cdb 'C:/Program Files (x86)/Windows Kits/10/Debuggers/x86/cdb.exe' `
  --helper C:/stand/com_cleanup77.dll --identity C:/stand/proxy_identity77.dll `
  --base C:/stand/base-for-test --copy-path C:/stand/harness77-copy --user ВВВ `
  --copy-exclude ExtForms --copy-exclude actofsverok --copy-exclude temp --format json
harness77 doctor --project project.toml --stand stand.toml --format json
harness77 run --project project.toml --stand stand.toml --output-root C:/runs/check
```

Выбирайте свои пути явно. Относительные CLI-пути разрешаются от CWD;
в профиле они абсолютные. Родитель output должен существовать, сам файл —
отсутствовать. Перезаписи/force нет. Команда не создаёт копию или замок,
не регистрирует базы/COM и не запускает 1С. Путь копии должен быть заранее
зарегистрирован; существующая копия или замок дают отказ. Idle guard сохраняется.
Профиль нельзя писать внутрь базы/копии. Пустой список исключений допустим.
В новом проекте требуется configuration.modules; каталог может быть пустым.
Выход нативного запуска должен оставаться ASCII без пробелов/разделителей CDB.

Пример квалифицирован на том же Windows-стенде, 1С 7.70.027 и CDB x86.
MD/DD и компоненты сверяются с принятой политикой runtime, неизвестная
база автоматически не одобряется. Работоспособность запуска подтверждает run.

Подготовка проверочного комплекта из принятых входов 092 (исходный комплект
не меняется, подготовка не запускает 1С):

```powershell
python -B examples/stand-init/prepare.py --inputs .artifacts/s92-kit-final --wheel .artifacts/s93-package/dist/harness77-0.3.0-py3-none-any.whl --output .artifacts/s93-kit
```

Комплект содержит wheel, входы, внешние DLL и проверяющий скрипт. Готовых
stand.toml, копий runtime и launcher в нём нет. Установка и проверка без checkout:

```powershell
$kit = 'C:/MyProjects/harness77/.artifacts/s93-kit'
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
python -m venv --without-pip "$kit/venv"
python -m pip --python "$kit/venv/Scripts/python.exe" install --no-index --no-deps "$kit/harness77-0.3.0-py3-none-any.whl"
& "$kit/venv/Scripts/python.exe" -B "$kit/run.py" --output C:/MyProjects/harness77/.artifacts/s93-final
```

inputs.json хранит выбранные параметры стенда. Скрипт передаёт их как явные
аргументы stand-init, проверяет JSON/текст, отрицательные пробы и отсутствие
изменений стенда. Затем оба созданных профиля проходят doctor, headless
возвращает 42, сценарий формы записывает/проводит документ и проверяет
сохранённые значения/проводки. Для повтора нужен новый output.
