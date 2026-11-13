# Прикладная регрессия через suite и MCP (097)

Один манифест выполняет baseline/regression/fixed/repeat-fixed из 096.
Неизменные UI-шаги и JSON-ожидания обнаруживают две ошибки сумм проводок.
Набор продолжает работу после failed/1; JUnit содержит один failure.
Через MCP такой результат имеет isError=false.

Отдельный набор invalid-json/empty-json/recovered возвращает blocked/2,
два JUnit error и разные причины повреждённого/пустого JSON. MCP сообщает
isError=true, отвечает на ping во время/после выполнения и затем успешно
выполняет новый suite. Каждый сценарий использует свежую копию базы.

```powershell
python -B examples/application-suite/prepare.py --structured .artifacts/s96-kit-release --output .artifacts/s97-kit
$kit = 'C:/MyProjects/harness77/.artifacts/s97-kit'
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
python -m venv --without-pip "$kit/venv"
python -m pip --python "$kit/venv/Scripts/python.exe" install --no-index --no-deps "$kit/harness77-0.5.0-py3-none-any.whl"
& "$kit/venv/Scripts/python.exe" -B "$kit/run.py" --output C:/MyProjects/harness77/.artifacts/s97-native
& "$kit/venv/Scripts/python.exe" -B "$kit/verify.py" C:/MyProjects/harness77/.artifacts/s97-native
```

Используется принятый wheel 0.5.0 без изменений ядра/runtime. Комплект
содержит входы 096, независимые verifier и небольшой stdio JSON-RPC клиент
без внешних зависимостей. MCP-сервер и дочерние CLI работают из установленного
venv, с другим CWD и без PYTHONPATH/PYTHONHOME. Полный трафик, прогресс и
ответы сохраняются. Готовая MD, база и собственный launcher в комплект не входят.

Независимая проверка перечитывает suite/JUnit, каждый run.json, raw протокол
UI и JSON. Сверяются точные поля диагностики, SHA-256, размеры и run_id,
плановая MD, все потоки конфигурации, один Initialize и очистка каждого
запуска. Сопоставление CLI/MCP исключает только переменные пути и run_id.
Источник, реестр, чужие процессы, входы и runtime должны сохраниться.
Автоматических повторов нет. Kit и output должны быть новыми каталогами.

Квалификация ограничена документом «Готовая продукция» и стендом Windows /
7.70.027 из 096; внесённая регрессия контролируемая, исходный модуль корректен.
