# Прикладной forms-проект через project-init (098)

Wheel 0.6.0 создаёт проект из явно выбранных ERT, UTF-8 модуля и JSON-сценария.
JSON содержит `parameters` и непустой `tests` в формате `[platform]` профиля:
включая UI-шаги, fixture setup/reader, `expect_value` либо `expect_json` и `json_labels`.
Бизнес-правила и ожидания задаёт автор сценария. Встроенного сценария для документа нет.

```powershell
harness77 project-init --runtime forms --directory C:/work/application77 --id application77 `
  --template C:/inputs/template.ert --source C:/inputs/form-module.1s --scenario C:/inputs/scenario.json `
  --open-timeout-s 240 --calculation-timeout-s 120 --cancel-timeout-s 15 `
  --shutdown-timeout-s 30 --total-timeout-s 600 --format json
harness77 doctor --project C:/work/application77/project.toml --stand C:/work/forms-stand.toml --format json
harness77 run --project C:/work/application77/project.toml --stand C:/work/forms-stand.toml --output-root C:/runs/direct
```

Профиль создаётся сразу со schema_version=2, относительными путями и прикладными
ожиданиями. Модуль, ERT и scenario.json копируются побайтно; configuration/ пуста.
Каталог публикуется целиком без перезаписи после проверки и перечитывания.
1С при инициализации не запускается. Стенд создаётся отдельно через stand-init
с runtime=forms. Работает прежний headless-вызов без --runtime.
Для изменений прикладных модулей используйте md-extract и configuration/.

Самостоятельный комплект использует принятые входы 097 и новый wheel:

```powershell
python -B examples/forms-project-init/prepare.py --application-suite .artifacts/s97-kit `
  --wheel .artifacts/s98-package/dist/harness77-0.6.0-py3-none-any.whl --output .artifacts/s98-kit
$kit = 'C:/MyProjects/harness77/.artifacts/s98-kit'
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:PYTHONNOUSERSITE = '1'
python -m venv --without-pip "$kit/venv"
python -m pip --python "$kit/venv/Scripts/python.exe" install --no-index --no-deps "$kit/harness77-0.6.0-py3-none-any.whl"
& "$kit/venv/Scripts/python.exe" -B "$kit/run.py" --output C:/MyProjects/harness77/.artifacts/s98-native
& "$kit/venv/Scripts/python.exe" -B "$kit/verify.py" C:/MyProjects/harness77/.artifacts/s98-native
```

Все семь проектов создаёт project-init; их профили, module.1s, template.ert и
scenario.json после команды не редактируются. Меняется только прикладной
модуль в configuration/: baseline/regression/fixed/repeat-fixed. Отдельные
сценарии invalid-json/empty-json/recovered сохраняют исходные ожидания.
Проверяются прямые run (passed/failed/passed), CLI suite и MCP suite,
JUnit, точные две диагностики, blocked при непригодном JSON, ping и следующий
успешный запрос MCP. Семь отказов инициализации не запускают 1С.

Verifier независимо перечитывает созданные файлы, входы, хеши и прикладные
ожидания, отчёты run/suite/JUnit, raw UI/JSON, плановые MD, один Initialize
и штатную очистку. Источник, реестр, чужие сеансы и входы сохраняются.
Квалификация ограничена документом «Готовая продукция» и стендом Windows /
7.70.027 из 096–097. Для повтора выберите новые kit/output.
