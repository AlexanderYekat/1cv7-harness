# Вкладки штатной формы счёта-фактуры (046)

Нужен checkout, закреплённый x86 DBF/1С 7.70.027/1С++ стенд и зарегистрированный
`copy_path`. Каждый сценарий использует новую проверенную копию базы.
Исходные MD, модули и диалоги сохраняются.

Генератор использует принятую подготовку и независимую сверку 043: три
расходные накладные; три ордера и два счёта-фактуры у второго основания.
Фактура выбирается по точной сохранённой ссылке из смешанного списка.
`journal_children` с `browse = true` передаёт её форму шагам просмотра.
После него разрешены только `tab`, `check`, `value`, `rows`, `total`;
ввод, запись, произвольные клавиши и повторное открытие отклоняются до 1С.

```toml
# В journal_children: browse = true, прежние kinds/limit/expected,
# reference = 23, caption_control = "кнПечать", caption_text = "Печать",
# browser_visible = false. Затем:
{ tab = "Табличная часть", browser_visible = true },
{ rows = 1 },
{ value = "Количество", row = 1, text = "1" },
{ value = "Сумма", row = 1, text = "50" },
{ total = "Сумма", text = "50" },
{ tab = "Шапка", browser_visible = false },
```

`tab` читает названия и выбранную страницу единственного видимого
`SysTabControl32` непосредственно в проверенном MDI-окне документа.
Имя сопоставляется без `&` и без учёта регистра; отсутствующее или неоднозначное
имя даёт отказ до отправки клавиш. Фокус и Left/Right направлены этому HWND
на private desktop. После каждой клавиши — ответ 1С и повторное чтение
выбранной страницы. Программного переключения слоя и TCM_SETCURSEL нет.
`browser_visible` требует нужную видимость таблицы после перехода.

Свидетельства — `tabs_before`, `tab_keys`, `tabs_after`, `tab_form`, `calls`.
Названия читаются через TCITEMA в собственной x86 1С; при тайм-ауте чтения
буфер остаётся до завершения своего сервера, чтобы исключить обращение
к освобождённой памяти. Клавиши при неизвестном результате не повторяются.
После шагов адаптер читает точную ссылку/вид/основание и сохранённые данные,
закрывает документ через WM_CLOSE без записи, затем список и подтверждает
возврат к исходному основанию. Это `viewing_return` шага `journal_children`.
При отказе шага возврат и очистка тоже проверяются. Последний `verify`
свежими объектами независимо читает документы и проводки.

```powershell
python -X utf8 -B examples/form-tabs/prepare.py --stand .local/s44a/stand.toml --output .local/form-tabs-new
python -X utf8 -B -m harness77 suite --suite .local/form-tabs-new/suite.toml --stand .local/form-tabs-new/stand.toml --output-root .artifacts/suites/form-tabs-new
python -X utf8 -B -m harness77 suite --suite .local/form-tabs-new/suite-missing.toml --stand .local/form-tabs-new/stand.toml --output-root .artifacts/suites/form-tabs-missing-new
python -X utf8 -B -m harness77 suite --suite .local/form-tabs-new/suite-rows.toml --stand .local/form-tabs-new/stand.toml --output-root .artifacts/suites/form-tabs-rows-new
```

Основной набор: первая фактура, вторая, повтор. Отрицательные наборы:
отсутствующая вкладка и ожидаемые две строки при фактической одной; каждый
продолжается успешным сценарием. `no-copy/project.toml` проверяет отказ без копии.
Генератор создаёт только профили, не запускает 1С.

Верификатор принимает каталог UUID с `suite.json`, возвращённый командой:

```powershell
python -X utf8 -B scripts/verify_form_tabs77.py --suite .artifacts/suites/form-tabs-new/<suite-uuid> --output .artifacts/form-tabs-new-verified.json
python -X utf8 -B scripts/verify_form_tabs_controls77.py --run .artifacts/suites/form-tabs-new/runs/<run-uuid> --output .artifacts/form-tabs-controls-new.json
```

Каталоги результатов должны быть новыми. Подробности —
[задание](../../docs/tasks/046-form-tabs.md) и
[техническая проверка](../../docs/tasks/046-form-tabs-acceptance.md).

## Запись и отмена правки счёта-фактуры (047)

Генератор с `--edit` создаёт два сценария для фактуры из слота 23
подготовки 043. Каждый получает свежую проверенную копию базы.
`journal_children edit = true` открывает точную ссылку, `tab` переключает
вкладку, а `cell` меняет количество в первой строке с 1 на 2.
Штатная формула пересчитывает сумму строки, «Всего» и итог с 50 до 100
при цене 50.

- `save` нажимает «Записать», закрывает документ и повторно открывает ту же
  ссылку. Таблица показывает количество 2 и суммы 100.
- `cancel` закрывает изменённую форму и отвечает «Нет» на вопрос
  «Сохранить Документ?». После повторного открытия той же ссылки таблица
  показывает исходные количество 1 и суммы 50.

После возврата в журнал команда `verify` читает документы и проводки
свежими объектами. Ожидание включает связь фактуры с основанием, её номер
и дату, состав подчинённых документов и состояние соседей.

```powershell
python -X utf8 -B examples/form-tabs/prepare.py --edit --stand .local/s44a/stand.toml --output .local/form-tabs-edit-new
python -X utf8 -B -m harness77 suite --suite .local/form-tabs-edit-new/suite.toml --stand .local/form-tabs-edit-new/stand.toml --output-root .artifacts/suites/form-tabs-edit-new
python -X utf8 -B scripts/verify_suite77.py --native .artifacts/suites/form-tabs-edit-new/<suite-uuid>
```

Подробности и результаты нативных проб — в [задаче 047](../../docs/tasks/047-invoice-table-edit.md).

## Правка второй строки (048)

`--edit-second-row` добавляет вторую строку к фактуре из слота 23.
Сценарии проверяют переход Down, изменение количества во второй строке
с 1 на 3 и итог 140 вместо 80. После записи повторное открытие показывает
изменённую строку, после «Нет» — исходную. В обоих случаях проверяются
первая строка и сохранённые данные соседних документов.

Отдельный `suite-row-guard.toml` оставляет курсор на строке 1.
`{ cell = "Количество", row = 2, text = "3" }` должен дать ожидаемый
отказ до ввода. Команда `verify` после отказа читает исходные значения.

```powershell
python -X utf8 -B examples/form-tabs/prepare.py --edit-second-row --stand .local/s44a/stand.toml --output .local/form-tabs-row2-new
python -X utf8 -B -m harness77 suite --suite .local/form-tabs-row2-new/suite.toml --stand .local/form-tabs-row2-new/stand.toml --output-root .artifacts/suites/form-tabs-row2-new
python -X utf8 -B -m harness77 suite --suite .local/form-tabs-row2-new/suite-row-guard.toml --stand .local/form-tabs-row2-new/stand.toml --output-root .artifacts/suites/form-tabs-row-guard-new
```

Ожидания и результаты — в [задаче 048](../../docs/tasks/048-invoice-second-row.md).
