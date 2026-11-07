# Несколько сценариев за один прогон (задача 029)

Пример объединяет неизменённые сценарии 025–028: шаги формы, модальные окна,
табличную часть документа и выбор ссылки. Требует checkout, исследовательский
launcher форм и закреплённый стенд 7.70.027 с зарегистрированным `copy_path`.

```powershell
python examples/scenario-suite/prepare.py --stand .local/stage21-native/stand.toml --output .local/stage29-example
python -m harness77 suite --suite .local/stage29-example/suite.toml --stand .local/stage29-example/form-steps/stand.toml
```

Подготовка не запускает 1С; выходной каталог должен быть новым. Исполнитель
последовательно выполняет четыре полных `run`, каждый на свежей удаляемой копии.
Каталог `.artifacts/suites/<suite_id>/` содержит `suite.json`, `junit.xml`.
Дочерние отчёты и свидетельства — `.artifacts/suites/runs/<run_id>/run.json`:
такая структура сокращает пути нативного launcher и не зависит от длины имени набора.

Минимальный манифест (пути от самого манифеста):

```toml
schema_version = 1

[suite]
id = "forms"

[[scenarios]]
id = "table"
project = "table-part/project.toml"

[[scenarios]]
id = "choice"
project = "reference-choice/project.toml"
```

Имена сценариев уникальны без учёта регистра. Один сценарий становится одним
JUnit testcase. Провал проверки даёт `failure`, ошибка входа или инфраструктуры —
`error`, сценарий после отмены или неподтверждённой очистки — `skipped`.
Ожидаемый отрицательный тест, прошедший по контракту `run`, остаётся успешным.
Коды процесса: 0 — все прошли, 1 — провал, 2 — блокировка или неполный набор.

`--output-root` меняет корень результатов, `--suite-id` задаёт имя нового каталога.
Ключи сроков `run` действуют на каждый сценарий отдельно. Ctrl+C или появление
нового файла `--cancel-file` отменяет текущий запуск и оставшуюся часть набора.
Автоматических повторов, параллельных сеансов и общих тестовых данных нет.
Профили с `configuration.keep_copy = true` отклоняются до запуска.

В CI укажите полученный `junit.xml` как файл результатов JUnit, а корень результатов
с каталогом набора и нужными `runs/<run_id>` сохраните как артефакт. Пути дочерних
отчётов записаны в JSON относительно каталога набора (`../runs/...`). Проверка:

```powershell
python scripts/verify_suite77.py .artifacts/suites/<suite_id> --native
```
