# Fixture и reader по TOML для «Счёта-фактуры»

`invoice.toml` описывает дату, товар, покупателя, договор, подразделение,
комментарий и строки документа. В секции `reader` перечислены итоговые поля
и поля строк. `render.py` создаёт два обычных файла сценария 1С 7.7.

```powershell
python -B examples/invoice-fixture/render.py --output .local/invoice111
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
`copy_path`. Запустите из окружения с установленным harness77 0.15.0.

```powershell
$python111 = '.artifacts/s110-release/download/venv/Scripts/python.exe'
$stand111 = '.artifacts/s104-release-native-project/stand.toml'
& $python111 -I -B examples/invoice-fixture/run.py `
  --project .artifacts/s111-invoice-project/project.toml --stand $stand111 `
  --output .artifacts/s111-invoice-cycle
```

В проверке один и тот же `expected.json` используется на всех трёх фазах.
На второй фазе модуль формы в копии базы записывает неверный комментарий.
Структурированный тест должен обнаружить `/comment_ok`. После возврата
исходного модуля сравнение проходит.
