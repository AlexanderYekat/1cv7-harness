# Структурированные прикладные проверки (096)

Проект возвращает JSON с сохранённым документом и проводками. В тесте
`expect_json` содержит ожидаемое дерево, `json_labels` — подписи JSON Pointer.
Проект объявляет `schema_version = 2`, чтобы прежний harness явно отказал
вместо игнорирования новой проверки. Старые проекты версии 1 продолжают работать.
Core сохраняет raw JSON, сравнивает поля и сообщает точные расхождения.
Деньги/количества здесь представлены строками, счётчики — JSON-числами.

Используется тот же документ и UI-сценарий 095. Изменяется одна строка
реального модуля проведения; исходная база корректна. Внесённая регрессия
даёт только два расхождения: «Проводка 1, сумма: ожидалось 30, получено 10»
и «Проводка 2, сумма: ожидалось 40, получено 20». Исправленный модуль совпадает
с исходным. Baseline/regression/fixed/repeat-fixed используют один тест.
Два отдельных отрицательных проекта возвращают повреждённый и пустой JSON;
для них ожидаются разные причины blocked/2. Эти проекты явно меняют reader,
а не ожидания основного теста.

```powershell
python -B examples/structured-checks/prepare.py --pilot .artifacts/s95-kit-final --wheel .artifacts/s96-package-release/dist/harness77-0.5.0-py3-none-any.whl --output .artifacts/s96-kit-release
$kit = 'C:/MyProjects/harness77/.artifacts/s96-kit-release'
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
python -m venv --without-pip "$kit/venv"
python -m pip --python "$kit/venv/Scripts/python.exe" install --no-index --no-deps "$kit/harness77-0.5.0-py3-none-any.whl"
& "$kit/venv/Scripts/python.exe" -B "$kit/run.py" --output C:/MyProjects/harness77/.artifacts/s96-final-release
```

Комплект самодостаточен после подготовки: в нём входы, wheel и независимые
verifier, без checkout-импортов, готовой MD, извлечённого прикладного модуля,
собственного launcher или копии runtime. Исполнение идёт из отдельного CWD
установленными stand-init/project-init/md-extract/md-build/doctor/run.
Каждый run использует свежую копию квалифицированной базы. Новые kit/output
должны отсутствовать. Внешние сеансы сохраняются как baseline; смена
инвентаря во время запуска останавливает проверку, автоматических повторов нет.

Сохраняются точные исходники и диффы, плановые MD и сверка всех потоков,
неизменность теста между четырьмя фазами, raw-протоколы UI, JSON с SHA-256,
диагностики и сверка сохранности базы/реестра/процессов/копии/замка.
Штатный runtime 0.5.0 использует прежние 33 нативных файла без изменений.
