# Разработка пакета

Python 3.11 или новее. Код продукта — `src/harness77`, тесты — `tests`,
обслуживание репозитория — `scripts`. Runtime-зависимостей нет.
Сборочный backend закреплён в `requirements-build.txt` и `pyproject.toml`.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-build.txt
.\.venv\Scripts\python -m pip install --no-build-isolation -e .
.\.venv\Scripts\python -B -m unittest discover -s tests -v
```

На Linux используйте `.venv/bin/python`. Для проверки поставки запускайте
[скрипт приёмки](testing.md); editable-установка не доказывает состав wheel.
Нормальная установка для потребителя: `python -m pip install .`, либо установка
собранного wheel с `--no-index --no-deps`. Для офлайн-сборки заранее сохраните
wheel закреплённого setuptools через `pip download -r requirements-build.txt`.

С задачи 092 штатный native runtime поставляется обычным wheel. Список
`native_catalog77.json` объявляет его 33 исходных файла; NativeBuild копирует
их в build/lib/harness77/_native и формирует манифест версии/SHA-256.
Исходники остаются в research, производные копии не редактируются вручную.
`verify_package77.py` проверяет сборку из sdist, точный состав и установку.
Для разработки исполнителя через checkout сохраняется явный launcher;
штатный режим проверяется установленным wheel без editable/PYTHONPATH.
[Установка и границы](tasks/092-installed-native-runtime.md).

Для прикладного проекта в 0.6.0 используйте
`project-init --runtime forms --source … --scenario …`: модуль и
parameters/tests задаются явными входами, профиль сразу готов для doctor/run.
Прежний вызов создаёт headless-проект. Изменения конфигурации помещайте
в созданную configuration/ после md-extract; сгенерированные профиль и
тестовый модуль не требуется переписывать.
[Пример полного цикла из wheel](../examples/forms-project-init/README.md).

Существующие `ert_module.replace_text` и операции диалога сохранены как внутренний
legacy-код с прежними ограничениями; публичная безопасная сборка —
`harness77.artifacts.build`, извлечение — `harness77.artifacts.extract`.
Не вызывайте прежнюю запись для новых продуктовых команд.

При изменении правил анализа добавляйте положительный, отрицательный и граничный
пример. Перенос/упаковка, смена алгоритма и новые правила — разные изменения.
JSON и коды возврата меняются вместе с контрактом и проверками совместимости.
Ресурсы читаются через `importlib.resources`, не из соседнего checkout.

Для новых текстовых файлов — UTF-8 без BOM и LF. Бинарные fixtures и точные
байты протоколов защищены `.gitattributes`. База, локальные профили и результаты
не входят в Git или sdist. Новые зависимости требуют явного назначения,
ограничений версии и отдельной проверки офлайн-пути.

Истории devtools и 77MCP сохраняются в исходных репозиториях; они больше
не требуются для обычной установки harness77. Не синхронизируйте копии кода
автоматически: последующие обновления импортируются осмысленно с происхождением.
