# Выбор документа среди нескольких подчинённых (042)

Пример требует checkout, закреплённый DBF-стенд 1С 7.70.027/1С++ и
зарегистрированный `copy_path`. Каждый запуск работает на новой проверенной
копии; исходные MD, модули и диалоги сохраняются.

Подготавливаются три похожих основания «Расходная накладная»: у первого
один приходный ордер, у второго три, у третьего ни одного. Все ордера имеют
одинаковые дату (1 августа 2026 года), сумму 50 и комментарий; номера выдаёт
платформа. Ссылки фиксируются непосредственно при подготовке. Два ордера
проведены с одной проводкой Дт 50.1 Кт 62.1, два не проведены.

```toml
{ journal_children = true, source = "РасходнаяНакладная", link = "ДокументОснование", reference = 17, limit = 100, journal = "Журнал.Общий.ФормаСписка.ФормаСписка", expected = "<исходное состояние>", caption_control = "ндСфетФактураУжеСформирована", caption_text = "Счет-факутра ещё не сформирована" }
```

Шаг следует непосредственно за `find_document` с `open = false`.
Наличие `limit` включает поиск End/Up: не более 1..100 чтений строк, включая
первую. Проверяются окно своего PID/TID, точные ссылки и принадлежность
основанию, исходное состояние всех подготовленных документов и проводок.
Повтор ссылки на границе списка завершает поиск отказом. Отсутствующая цель
или исчерпание лимита не отправляют Enter; список закрывается без записи.

При совпадении ссылки выполняется отдельное чтение перед Enter. Проверяется
новое окно сохранённого ордера, его ссылка и `ДокументОснование`. После закрытия
без записи проверяются возврат в список, затем в исходный журнал, отсутствие
лишних окон и независимое сохранённое состояние. `cancel = true` выполняет
поиск и повторное чтение, затем закрывает список без Enter. `empty` с `limit`
не допускается. Прежний режим 041 без `limit` проверяет единственность строки.

```powershell
python -X utf8 examples/journal-children-selection/prepare.py --stand .local/s40j/stand.toml --output .local/journal042
python -X utf8 -m harness77 suite --suite .local/journal042/suite.toml --stand .local/journal042/stand.toml --output-root .artifacts/suites/journal042-main
python -X utf8 -m harness77 suite --suite .local/journal042/suite-failure.toml --stand .local/journal042/stand.toml --output-root .artifacts/suites/journal042-failure
python -X utf8 -m harness77 suite --suite .local/journal042/suite-reference.toml --stand .local/journal042/stand.toml --output-root .artifacts/suites/journal042-reference
python -X utf8 -m harness77 suite --suite .local/journal042/suite-limit.toml --stand .local/journal042/stand.toml --output-root .artifacts/suites/journal042-limit
```

Основной набор проверяет первую, среднюю и последнюю строки обхода End/Up,
повтор на новой копии и отмену. Три отрицательных набора дают ожидаемый failure
JSON/JUnit и успешное продолжение: неверная проводка, ссылка ордера другого
основания, лимит 1 при цели во второй строке. `no-copy/project.toml` проверяет
отказ до запуска 1С без проверенной копии.

`scripts/verify_journal_children_selection77.py` независимо перечитывает сырые
ответы/протоколы, команды, окна, поиск и повторное чтение, данные, JSON/JUnit,
хеши и очистку. `verify_journal_children_selection_controls77.py` проверяет
подмены этих свидетельств. Результаты нативной проверки и ограничения —
в [отчёте 042](../../docs/tasks/042-journal-children-selection-acceptance.md).
