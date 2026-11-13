# Локальный проект и harness77.txt (099)

Подробная инструкция поставляется с wheel и копируется в проект:
[local_project77.md](../../src/harness77/local_project77.md).
Skills, глобальные AGENTS/настройки Codex и регистрация MCP не требуются.

Первое подключение существующего проекта из установленного дистрибутива:

```powershell
python -m harness77 connect --directory C:/work/application --wheel C:/releases/harness77-0.7.0-py3-none-any.whl --bundle --format json
python C:/work/application/.harness77/launch.py status --format json
python C:/work/application/.harness77/launch.py doctor --format json
python C:/work/application/.harness77/launch.py run
python C:/work/application/.harness77/launch.py suite
python C:/work/application/.harness77/launch.py mcp
```

Автообнаружение читает корневые TOML с `[project]`, `[stand]`, `[suite]`;
несколько кандидатов требуют явного пути. Профили можно задать при подключении
через `--project`, `--stand`, `--suite`. Stand хранит существующую базу;
новая исходная база не создаётся. Относительные ссылки хранятся от config.json.
Параметры операции можно передать после её имени; failed/blocked сохраняются.

Для внешнего wheel уберите `--bundle`; для установленной поставки используйте
`--external-python C:/tools/h77/Scripts/python.exe`. Для скачивания нужны
`--version 0.7.0 --url <конкретный asset wheel> --sha256 <доверенный SHA-256>`.
GitHub Releases подходит; адрес опубликованного релиза и итог проверки указаны
в [приёмке 099](../../docs/tasks/099-local-project-activation-acceptance.md).
Пустой `harness77.txt` включает новые обращения, удаление выключает их,
в том числе новые tools/call открытого MCP. Сам маркер ничего не запускает.

Воспроизведение поставки и получения пакета (выбирайте новые output):

```powershell
python -B scripts/verify_package77.py --output .artifacts/s99-distribution --command-timeout-s 600
python -B scripts/verify_local_activation77.py --wheel .artifacts/s99-distribution/dist/harness77-0.7.0-py3-none-any.whl --installed-python .artifacts/s99-distribution/venv/Scripts/python.exe --template .artifacts/s98-kit/inputs/template.ert --output C:/MyProjects/h77-099-local
```

Без `--url` verifier запускает настоящий локальный HTTP-сервер, скачивает wheel
через pip, затем закрывает сервер и повторяет работу из кеша. Это не подменяет
проверку опубликованного GitHub asset: для неё передайте URL существующего
релиза. Проверяются оба внешних пути, bundled wheel, загрузка, отсутствие
маркера до получения, удаление маркера после работы, живой MCP, неверный хеш,
повреждение кеша, сеть без подходящего кеша, параллельная подготовка и перенос.
Внутренний транспорт этой серии — simulation; нативная серия отдельная.

Самостоятельный нативный комплект по входам 097, без исходного checkout:

```powershell
python -B examples/forms-project-init/prepare.py --application-suite .artifacts/s97-kit --wheel .artifacts/s99-distribution/dist/harness77-0.7.0-py3-none-any.whl --output C:/MyProjects/h77-099-kit
python -m venv --without-pip C:/MyProjects/h77-099-kit/venv
python -m pip --python C:/MyProjects/h77-099-kit/venv/Scripts/python.exe install --no-index --no-deps C:/MyProjects/h77-099-kit/harness77-0.7.0-py3-none-any.whl
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
C:/MyProjects/h77-099-kit/venv/Scripts/python.exe -B C:/MyProjects/h77-099-kit/run.py --local-activation --output C:/MyProjects/h77-099-native
C:/MyProjects/h77-099-kit/venv/Scripts/python.exe -B C:/MyProjects/h77-099-kit/verify.py C:/MyProjects/h77-099-native
```

doctor/run/CLI suite и MCP идут через `.harness77/launch.py`; инициализация
входов и сборка планов используют установленный дистрибутив. Повторяется
прикладной цикл 098: три прямых run, регрессия/исправление/повтор и непригодный
JSON через CLI/MCP, следующий успешный MCP suite и удаление маркера у живого
сервера. Verifier перечитывает MD, raw JSON/UI, JUnit, очистку и сохранность
источника/реестра/чужих процессов. Квалификация ограничена прежним документом
«Готовая продукция» и Windows / 7.70.027.
