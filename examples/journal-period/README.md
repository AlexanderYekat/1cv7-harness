# Пример 036: период журнала и документ вне исходного интервала

Закреплённые DBF-стенд `base-for-test`, 1С 7.70.027 и установленный 1С++.
Нужен checkout; каждый run использует новую проверенную копию базы.
Модули и диалоги конфигурации исходные.

Подготовка создаёт три проведённых документа «Готовая продукция»: сосед
31 июля 2026 года, цель и второй сосед 1 августа. По две строки и проводки
Дт 43 Кт 40, итог 50. Исходный интервал журнала «Материалы» заканчивается
31 июля; цель в нём отсутствует.

Шаг `{ journal_period = true, start = "2026-07-31", end = "2026-08-01" }`
посылает штатную команду «Интервал» (`0x8071`, меню установленной платформы).
Наблюдатель проверяет MDI-рамку своего журнала, окно «Параметры журнала»,
два непосредственных поля BMASKED (4674/4676) и их редакторы 1CEDITSPR.
Вводит даты через клавиатурные сообщения и нажимает OK. С `cancel = true`
нажимает «Отмена». До и после отдельно читает НачалоИнтервала/КонецИнтервала;
номера вызовов уникальны, ответы и протоколы сохраняются. Программной установки
интервала нет. Даты профиля — ISO; нативно проверены указанные даты 2026 года.

`journal_period` допускается только перед `find_document` в режиме
`journal_existing`. Последующий поиск и цикл формы соответствуют 035:
End/Up → точная ссылка → Enter → правка → запись/перепроведение → reopen →
независимое чтение трёх документов и проводок.

```powershell
python -X utf8 examples/journal-period/prepare.py --stand .local/s35e/stand.toml --output .local/journal036
python -m harness77 suite --suite .local/journal036/suite.toml --stand .local/journal036/stand.toml --output-root .artifacts/suites/journal036-main
python -m harness77 suite --suite .local/journal036/suite-failure.toml --stand .local/journal036/stand.toml --output-root .artifacts/suites/journal036-negative
python -m harness77 suite --suite .local/journal036/suite-limit-failure.toml --stand .local/journal036/stand.toml --output-root .artifacts/suites/journal036-excluded
python -m harness77 suite --suite .local/journal036/suite-cancel-failure.toml --stand .local/journal036/stand.toml --output-root .artifacts/suites/journal036-cancel
```

Основной набор — успех и повтор. В каждом отрицательном наборе один failure
и следующий успешный сценарий: неверное ожидание количества; период 31 июля,
исключающий цель; отмена введённых дат, сохраняющая исходный интервал.
Оба отрицательных поиска ограничены тремя переходами и не отправляют Enter;
независимое чтение подтверждает исходные данные/проводки. `no-copy/project.toml`
блокируется до 1С. Отмена изменённой формы документа остаётся регрессией 035.

`scripts/verify_journal_period77.py` принимает четыре `--suite UUID_DIR`,
`--blocked-run UUID_DIR`, `--output NEW_JSON`, а также `--excluded-run`,
`--test-log`, `--regression-report`. Перечитывает сырые ответы и протоколы
всех шагов, JSON/JUnit, начальное/конечное состояние, хеши и очистку.
Проверяет исключение цели исходным периодом, ввод обеих дат, OK/«Отмена»,
отсутствие Enter при провале и сохранность соседей.
