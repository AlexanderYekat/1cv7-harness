# Пример 034: создание документа из журнала

Закреплённые DBF-стенд `base-for-test`, платформа 7.70.027, 1С++ и
зарегистрированный `copy_path`. Нужен checkout: launcher находится в `research/forms`.
Модули и диалоги конфигурации остаются исходными; каждый run работает на новой копии.

Подготовка создаёт только товар и считает документы. Сценарий открывает
журнал «Материалы», нажимает Insert и выбирает точный пункт
«Гот.прод. (Передача готовой продукции на склад)» в штатном окне выбора вида.
Контроллер подтверждает новую незаписанную форму `Документ.ГотоваяПродукция`,
наблюдатель независимо сопоставляет её HWND и описание из MD.

Через интерфейс выбирается товар, вводятся две строки 3 × 10 и 2 × 20,
комментарий «Harness77 журнал 034». «Записать» сохраняет документ;
`created` получает его ссылку и новым объектом проверяет наличие записи.
«ОК» и «Да» на «Провести документ?» проводят и закрывают новую форму.
`reopen` открывает ту же сохранённую ссылку. Проверяются поля и итог 70;
независимое чтение подтверждает один новый документ и две проводки Дт 43 Кт 40.

Отмена: новая форма получает комментарий, «Закрыть» открывает вопрос
«Сохранить Документ?», ответ «Нет» закрывает форму. Проверка возвращает
`0|none`: число документов не изменилось, ссылка не получена.

## Запуск

Профиль стенда должен содержать абсолютные пути и зарегистрированный `copy_path`.
Выберите новый каталог `--output`:

```powershell
python -X utf8 examples/journal-document/prepare.py --stand .local/s33g/stand.toml --output .local/journal034
python -m harness77 suite --suite .local/journal034/suite.toml --stand .local/journal034/stand.toml --output-root .artifacts/suites/journal034-main
python -m harness77 suite --suite .local/journal034/suite-failure.toml --stand .local/journal034/stand.toml --output-root .artifacts/suites/journal034-negative
python -m harness77 suite --suite .local/journal034/suite-reopen-failure.toml --stand .local/journal034/stand.toml --output-root .artifacts/suites/journal034-reopen-negative
```

Основной набор: успех, повтор, отмена. Отрицательные наборы: неверное ожидание
сохранённого количества либо комментария повторно открытой формы и следующий
успешный сценарий. Ожидаемый код этих наборов — 1, ровно один JUnit failure.
`no-copy/project.toml` должен получить blocked/2 до запуска 1С.

Независимая сверка завершённых каталогов наборов (с UUID, не их корней):

```powershell
python scripts/verify_journal_document77.py --suite MAIN_UUID_DIR --suite NEGATIVE_UUID_DIR --suite REOPEN_NEGATIVE_UUID_DIR --blocked-run NO_COPY_RUN_DIR --output .artifacts/journal034-check.json
```

Проверяются сырые ответы/протоколы, UI-переход и HWND, ссылка, поля и проводки,
JSON/JUnit, хеши и очистка. `--test-log`, `--excluded-run`, `--excluded-test-log`
и `--regression-report` связывают дополнительные свидетельства.

Это проверка одного документа и штатного окна выбора вида на данном стенде.
Другие журналы, виды документов, варианты окна выбора и SQL не проверены.
