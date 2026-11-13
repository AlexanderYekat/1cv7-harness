# Минимальный проект из установленного пакета (094)

`harness77 project-init` в wheel 0.4.0 принимает новый directory, id,
существующий шаблон ERT и пять явных сроков. Создаёт project.toml,
module.1s, побайтную template.ert и пустую configuration/ для headless.
Стенд и проект создаются отдельно, затем проверяются явно:

```powershell
harness77 stand-init --output stand.toml --name local --runtime headless `
  --exe 'C:/Program Files (x86)/1Cv77/BIN/1cv7l.exe' `
  --cdb 'C:/Program Files (x86)/Windows Kits/10/Debuggers/x86/cdb.exe' `
  --helper C:/stand/com_cleanup77.dll --identity C:/stand/proxy_identity77.dll `
  --base C:/stand/base-for-test --copy-path C:/stand/harness77-copy --user ВВВ `
  --copy-exclude ExtForms --copy-exclude actofsverok --copy-exclude temp
harness77 project-init --directory C:/work/hello77 --id hello77 `
  --template C:/stand/FIO.ERT --open-timeout-s 120 --calculation-timeout-s 60 `
  --cancel-timeout-s 15 --shutdown-timeout-s 30 --total-timeout-s 300 --format json
harness77 doctor --project C:/work/hello77/project.toml --stand stand.toml --format json
harness77 run --project C:/work/hello77/project.toml --stand stand.toml --output-root C:/runs/check
```

Укажите собственные пути явно. Родитель проекта должен существовать;
существующий каталог, даже пустой, не заменяется. ID — ASCII-буквы/цифры,
точки, дефисы и подчёркивания, до 64 символов; начинается с буквы/цифры,
не оканчивается точкой, не имя устройства Windows. Проект публикуется
целиком после проверки. Шаблон не меняется, 1С при инициализации не запускается.
Проверка контейнера ERT не подтверждает выполнение в 1С — это делает run.

Результат исходника — 42, ожидание записано в project.toml. Чтобы проверить
отрицательный случай, в отдельном созданном проекте измените только
expect_value на 999: настоящий execute остаётся 42, итог запуска — failed/1.
Нативный стенд квалифицирован для Windows, 1С 7.70.027 и CDB x86; нужна
зарегистрированная копия базы. Output нативного запуска — ASCII без пробелов.

Самостоятельный проверочный комплект из принятых входов 093:

```powershell
python -B examples/project-init/prepare.py --inputs .artifacts/s93-kit --wheel .artifacts/s94-package/dist/harness77-0.4.0-py3-none-any.whl --output .artifacts/s94-kit
```

В комплекте только wheel, явные параметры стенда, внешние DLL, входной
шаблон и проверяющий скрипт. Готовых проектов, модулей и runtime-копий нет.
Установка и проверка без checkout:

```powershell
$kit = 'C:/MyProjects/harness77/.artifacts/s94-kit'
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
python -m venv --without-pip "$kit/venv"
python -m pip --python "$kit/venv/Scripts/python.exe" install --no-index --no-deps "$kit/harness77-0.4.0-py3-none-any.whl"
& "$kit/venv/Scripts/python.exe" -B "$kit/run.py" --output C:/MyProjects/harness77/.artifacts/s94-final
```

Скрипт выполняет stand-init, project-init (JSON/текст), отрицательные пробы,
doctor и настоящие запуски: успех, неверное ожидание и успех после него.
Все проекты создаются командой; ручное изменение ограничено одним
намеренно неверным ожиданием. Источник, реестр, процессы, копия/замок/guard
и входной комплект сверяются до/после. Для повтора выберите новые каталоги.
