# Перепроведение и отмена проведения (задача 031)

Пример для закреплённого стенда 7.70.027: «Готовая продукция», Дт 43 Кт 40.
Каждый сценарий выполняется на новой проверенной копии базы.

```powershell
python examples/document-lifecycle/prepare.py --stand .local/stage21-native/stand.toml --output .local/s31
python -m harness77 suite --suite .local/s31/suite.toml --stand .local/s31/stand.toml
python -m harness77 suite --suite .local/s31/suite-failure.toml --stand .local/s31/stand.toml
```

Выходной каталог подготовки должен быть новым. Требуются checkout, нативный
launcher форм и зарегистрированный `copy_path` стенда. Срок открытия 240 с,
расчёта 120 с, общий 600 с. Автоматических повторов нет.

`suite` выполняет полный цикл, ожидаемую ошибку перед повторным проведением и
полный цикл на свежей копии. `suite-failure` подтверждает неверное ожидание
проводок и продолжение успешным сценарием (код выхода 1).

В `[platform.parameters]` список `fixture_operations` задаёт операции:

```toml
fixture_operations = [
    { id = "first", action = "post" },
    { id = "cancel", action = "unpost" },
]
```

Требуются `fixture_setup`, `fixture_verify`, форма документа, `[configuration]`
и явные тесты `post-first`, `verify-first`, `unpost-cancel`, `verify-cancel`,
`verify`. Существующий `fixture_post` с этим списком несовместим.
Возврат и сохранённый признак проведения записываются в `posting` операции;
успех проведения — `1|1`, отмены — `1|0`. Проверка проводок независима.
Проводки читаются после каждой операции по той же ссылке документа.

Необязательный `before` — доверенный код 1С над заново прочитанным
`Док77Проведения`. Для изменения данных код явно записывает документ.
Генератор демонстрирует изменение первой строки с 3/30 на 5/50.
Обработка интерфейсных кнопок и других документов отдельно не проверяется.

Независимая проверка JSON/JUnit, проводок, протоколов и очистки:

```powershell
python scripts/verify_lifecycle77.py --suite .artifacts/suites/<id> --output .artifacts/stage31-verification.json
```
