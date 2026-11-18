# Fixture и reader по описанию для «Оказания услуг»

В `services.toml` задаются дата, имена связанных записей, комментарий,
тип услуги и строки документа. Там же перечислены числовые реквизиты шапки,
итоги и поля строк для чтения. Имена реквизитов берутся из конфигурации 1С.
Поля `integers` читаются как целые числа JSON. `totals` и `rows` сохраняют
представление числовых полей строками, как в примере 104.
Порядок создания справочников, владелец договора и нулевые ставки описаны
один раз в `render.py`.

```powershell
python -B examples/services-fixture/render.py --output .local/services110
```

Команда создаёт в новом каталоге `fixture.1s` и `reader.1s`. Подключите их в
профиле рабочего сценария «Оказание услуг» через `fixture_setup_file` и
`fixture_verify_file`. Для UI используется `steps.json` из примера 104, для
теста `verify` — `expected.json` из этого примера. При изменении рецепта
отредактируйте ожидаемый результат отдельно. Reader открывает новый объект
документа по точной ссылке fixture и читает записанные данные после UI.

`run.py` воспроизводит проверку задачи на квалифицированном Windows / 1С
7.70.027 / DBF-стенде. Передайте профиль работающего примера 104 и его stand
с `runtime = "forms"` и `copy_path`. Используйте Python с установленным
`harness77` 0.15.0. Пример для локальных артефактов квалификации:

```powershell
$python110 = '.artifacts/s110-release/download/venv/Scripts/python.exe'
$services110 = '.artifacts/s104-release-native-project'
& $python110 -I -B examples/services-fixture/run.py `
  --project "$services110/project.toml" --stand "$services110/stand.toml" `
  --output .artifacts/s110-services-cycle
```

В цикле `baseline → regression → fixed` меняется только модуль формы в
собранной копии конфигурации. Регрессия записывает `ТипУслуги = 2` в
`ПриЗаписи`; UI проходит, структурированный тест находит `/service_type`.
Исправление возвращает исходный модуль при тех же входах. Запуски и сравнение
сохранены в `verified.json` выходного каталога.
