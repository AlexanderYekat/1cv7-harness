# Fixture и reader по TOML для «Счёта-фактуры»

[Образец invoice.toml](../../src/harness77/fixture_recipes/invoice.toml) описывает
дату, товар, покупателя, договор, подразделение, комментарий и строки документа.
В секции `reader` перечислены итоговые поля и поля строк. Команда `fixture-render`
создаёт два обычных файла сценария 1С 7.7.

```powershell
harness77 fixture-render --kind invoice --output .local/invoice111
```

В профиле прямого сценария укажите созданные файлы в `fixture_setup_file`
и `fixture_verify_file`. Шаги и ожидания можно взять из примера 103.
Они хранятся отдельно от рецепта. Reader заново открывает документ по ссылке
fixture и читает сохранённые значения после записи из формы.
[Прямой сценарий 103](../invoice-project/README.md).

С «Оказанием услуг» общие создание контрагента, договора и подразделения,
запись шапки и строк и формирование JSON. В коде счёта-фактуры остаётся
назначение типа ссылки для `Товар`. Нулевые ставки по-прежнему задаёт рецепт
услуг. [Рецепт «Оказание услуг»](../services-fixture/README.md).

`run.py` воспроизводит цикл нативной проверки. Передайте профиль рабочего
прямого сценария счёта-фактуры и профиль стенда с `runtime = "forms"` и
`copy_path`. Запустите из окружения с установленным harness77 0.16.0.

```powershell
$qualification = 'C:/MyProjects/h77-112-qualify'
& "$qualification/venv/Scripts/python.exe" -I -B examples/invoice-fixture/run.py `
  --project "$qualification/invoice-project/project.toml" --stand "$qualification/stand.toml" `
  --recipe "$qualification/invoice.toml" --output .artifacts/s112-invoice-replay
```

В проверке один и тот же `expected.json` используется на всех трёх фазах.
На второй фазе модуль формы в копии базы записывает неверный комментарий.
Структурированный тест должен обнаружить `/comment_ok`. После возврата
исходного модуля сравнение проходит.
