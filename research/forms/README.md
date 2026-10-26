# Формы ERT и 1Cv7.MD в настоящей 1С 7.7 (задачи 008, 010–013, 022–026)

Исследовательская часть [задачи 008](../../docs/tasks/008-form-description.md):
открыть форму собранной ERT видимой в своём сеансе 1С, сверить окна элементов
с описанием формы и нажать кнопку. Описание и сборка формы — в продукте
(`harness77 form-extract`, `build --form`); здесь только нативная проверка
поверх launcher этапа 4.

## Файлы

- `form_launcher77.py` — адаптер формы к `stage4_launcher77`. Команды `check`
  (открыть и закрыть), `open` (открыть и оставить), `result` (прочитать
  `Форма.Параметр` и закрыть). Перед `result` клиент ждёт маркер
  `form-click-done`: 1С простаивает в цикле сообщений, пока наблюдатель жмёт.
  `[platform.parameters] click_id` — ID записи кнопки в описании.
- `form_window77.py` — окна своего процесса на своём desktop (правила
  `OwnedModal`: идентичность процесса перепроверяется перед сообщением),
  геометрия в клиентской области родителя, DPI, `BM_CLICK` через
  `SendMessageTimeoutW`. Переносимые `window_ids`, `fit_units`, `judge_layout`.
- `probe_module77.1s` — модуль пробы для FIO.ERT: `Harness77Нажатие` добавляет
  `clicked:<n>` в параметр формы и сообщает о нажатии; `Harness77Пусто` — пустой
  обработчик для отрицательной пробы.
- `prepare_cases77.py` — локальные описания (`fio-*.json`) и профили F0–F4
  из закреплённого FIO.ERT; машинные пути остаются в `.local`.
- `diagnose_controller77.py` — компиляция текста контроллера вложенным
  `ВыполняемыйМодуль` с сохранением протокола: так получен текст ошибки,
  когда `Compile()` клиента вернул только 0.
- `verify_corpus77.py` — обратное преобразование всех форм локального корпуса.

Задача 025 ([сценарии шагов](../../docs/tasks/025-form-steps.md)):

- `scenario77.py` — `[platform.parameters] steps`: разбор и проверка шагов, разрешение элементов
  по описанию формы, функция контроллера `Harness77Step`, ожидание клиента с обслуживанием шагов,
  оценка шага и итог `result`. Переносимый код, тесты — `tests/test_scenario77.py`.
- `form_launcher77.py` — режим шагов: наблюдатель выполняет шаг, просит клиента вызвать 1С
  (файл `form-step-request`, ответ `form-step-<n>-done`), читает сообщения шага и окна.
  Протокол harness77 модулю формы не нужен.
- `form_window77.py` — `enter_text` (фокус, выделение, ввод, выход из поля), `focused`, `alive`,
  `element_state`.
- `steps_module77.1s` — модуль FIO.ERT без протокола harness77 для случая `s-ert`.
- `probe_scenario77.py` — серии проб 025 поверх `probe_md_forms77.run_series` (свои подготовка и
  оценка); `scripts/verify_form_steps77.py` — сводная проверка.

Задача 026 ([модальные окна в шагах](../../docs/tasks/026-modal-dialogs.md)):

- `scenario77.py` — шаг `dialog` и порядок цепочки «действие → окна», выбор кнопки и поля окна,
  безопасный ответ, номера и объединение вызовов 1С цепочки, оценка.
- `form_window77.py` — `Pending` (последнее сообщение действия из своего потока), `click_pending`,
  `enter_text` с отложенным выходом из поля и `left`, `top_windows`, `modal_window`, `window_record`,
  `await_action`, `answer` (ввод в поле окна и `WM_COMMAND` от кнопки).
- `form_launcher77.py` — `Chain`: действие и его окна; после возврата действия вызов 1С и поиск окна,
  которое открыло поставленное в очередь (`settle`); закрытие окон провалившегося шага (`dismiss`).
- `modal_module77.1s` — модуль FIO.ERT с вопросом в «Очистить» для случая `m-ert`.
- `probe_modal77.py` — серии проб 026 (подготовка и оценка — `probe_scenario77`);
  `scripts/verify_modal_dialogs77.py` — сводная проверка.

Задача 023 ([формы справочников и журналов](../../docs/tasks/023-catalog-journal-forms.md)):

- `form_launcher77.py` — `form_object` называет форму как файл её модуля: `Справочник.<Вид>.ФормаЭлемента`
  и `…ФормаГруппы` открывают новый элемент и новую группу (`ОткрытьФорму("Элемент.<Вид>", Контекст[, , 1])`),
  `Справочник.<Вид>.ФормаСписка.<Форма>` и `Журнал.<Имя>.ФормаСписка.<Форма>` — форму списка; у формы
  списка в ожидаемом описании — место списка (`browser`). Отказ до запуска 1С: новый элемент или группа
  подчинённого справочника (нужен владелец), форма элемента справочника, который редактируется в списке
  (поле 11 записи — 0: 1С её не открывает, `ОткрытьФорму` возвращает пустое значение).
- `form_window77.py` — окно дерева групп формы списка (`SysTreeView32`) — ID 4679, его место в очереди окон
  сохраняется; масштаб подбирается по положениям и размерам элементов вместе.
- `probe_md_catalogs77.py` — серии проб задачи 023 поверх `probe_md_forms77.py` (форма без своей
  `ПриОткрытии` получает её; строка ошибки модуля сверяется с журналом копии; ожидание `blocked`).

```powershell
python -B research/forms/probe_md_catalogs77.py --stand .local/stage21-native/stand.toml --work .local/stage23-native/NEW `
  --evidence .artifacts/stage23-catalog-forms-YYYYMMDD-N.json [--case e-button ...] [--dry-run]
```

Задача 022 ([формы `1Cv7.MD`](../../docs/tasks/022-md-forms.md)):

- `form_launcher77.py` — `[platform.parameters] form_object = "Обработка.<Имя>"` (или `Документ.<Имя>`,
  `Отчет.<Имя>`; формы справочников и журналов — задача 023): контроллер открывает форму конфигурации, ожидаемый диалог берётся из `1Cv7.MD`
  открытой базы (копии прогона) вместе с местом табличной части (`browser`); окружение снимка —
  конфигурация базы стенда.
- `form_window77.py` — ID окон формы с табличной частью (окна идут с последней записи, табличная
  часть — после первых `B` окон, её колонки занимают `C` номеров); поля `1CEDIT`/`BMASKED`
  сравниваются без рамки в 1 px; в ANSI-окно поля символ уходит байтом Windows-1251
  (`SendMessageTimeoutA`), а не по раскладке потока 1С; надпись с формулой с подписью не сверяется.
- `probe_md_forms77.py` — серии проб: модуль формы с протоколом проб, изменённое описание,
  один `harness77 run` с `[configuration]` на случай; `--dry-run` собирает конфигурации без 1С.

Задача 010 ([визуальные тесты](../../docs/tasks/010-visual-form-tests.md)):

- `form_launcher77.py` принимает `--captures-json` (состояния `open`/`clicked`,
  окна `form`/`dialog`): показывает главное окно своей 1С без активации, снимает
  состояние `open`, нажимает `click_id`, снимает `clicked`, скрывает окно. Снимки —
  `<run>/form/capture-<state>-<window>.png`, записи — `captures` в `form-window.json`.
  `[platform.parameters] visual_probe = true` — проба V0 (все способы снимка до
  и после показа, `visual-*.png`).
- `form_window77.py`: `show` (`ShowWindowAsync` с перепроверкой идентичности),
  `capture` (`PrintWindow` в DIB), `on_desktop` (вызов в потоке, подключённом
  к desktop сеанса), `caret` (`GetGUIThreadInfo`), `environment` (среда снимка).
- `visual_module77.1s` — модуль проб: «Проверка» пишет «Нажато: <n>» в поле «Фамилия».
- `prepare_visual77.py` — локальные профили V1–V6 и эталоны с чужой средой для V6.
- `verify_visual77.py` — приёмка по свидетельствам V0–V6.

Задача 011 ([новые элементы](../../docs/tasks/011-form-elements.md)):

- `form_launcher77.py`: `[platform.parameters] actions` — `click:<ID>` и
  `type:<ID>=<текст>` через запятую (`click_id` — сокращение для одного нажатия);
  текст полей и состояние флажков до и после действий (`fields_open`,
  `fields_after`), сверка подписей окон; значение `result` — все строки обработчиков.
- `form_window77.py`: `type_text` (`WM_CHAR` во вложенное окно поля, `editor`),
  `text` (`WM_GETTEXT`), `checked` (`BM_GETCHECK`), `judge_captions`; осмотр
  записывает дочерние окна элементов.
- `elements_module77.1s` — модуль проб E1–E3; `conflict_module77.1s` и
  `conflict_value_module77.1s` — `Перем Фамилия` при поле «Фамилия» (E4, E4b).
- `prepare_elements77.py` — описания и профили E1–E4b; `verify_elements77.py` — приёмка.

Задача 012 ([ссылочные поля](../../docs/tasks/012-reference-fields.md)):

- `form_launcher77.py`: строки обработчиков `repr:<имя>=<текст>` (представление
  значения зависит от данных базы) не входят в значение `result`, а пишутся
  в `representations` операции; приёмка сверяет их с текстом окон полей.
- `references_module77.1s` — модуль проб R1–R3: значения базы в шести ссылочных
  полях, «Проверка» сообщает тип, вид, совпадение с исходным и пустоту.
- `references_foreign77.1s` — модуль ручной проверки в любой базе: данных не читает,
  «Проверка» выводит `Сообщить` тип, вид и значение шести полей. Сборка —
  `harness77 build` с ERT прогона R1 как шаблоном (форма и копия метаданных те же).
- `prepare_references77.py` — описания (вид по имени), FIO.ERT с копией метаданных
  ERT корпуса (R5) и профили R1–R5;
  `verify_references77.py` — приёмка.
- `verify_corpus77.py --metadata 1Cv7.MD` — обратное преобразование корпуса
  с именами видов вместо номеров.

Задача 013 ([сверка видов по именам](../../docs/tasks/013-kind-name-checks.md)):

- `kinds_module77.1s` — модуль проб K1–K5 для `Договор_Оргтехники.ert`: данных
  не читает, при открытии пишет `value:<поле>=<ТипЗначенияСтр>|<Вид()>` по каждому
  полю вида (вне harness — `Сообщить`); строку-метку полей подготовка заменяет
  вызовами по полям случая.
- `prepare_kinds77.py` — описания K1–K3 (без правок, + `Документ.Выписка`,
  + `Справочник.ТипыЦен`), шаблон K5 с копией метаданных базы без перевода номеров
  и профили K1–K5b; K4 — `[build] metadata` другой конфигурации (только чтение).
- `verify_kinds77.py` — приёмка по свидетельствам K1–K5b и трём сверкам корпуса.
- `verify_corpus77.py`: виды всегда называются по копии ERT; с `--metadata`
  в итогах — число видов, отсутствующих в базе, форм с ними и видов с другим номером.

## Что установлено (стенд 7.70.027, Windows 11, 96 DPI)

- **ID окон не равны полю 9 записи.** Окно записи с индексом i из N получает
  ID 4152 + N − 1 − i (последняя запись — 4152). Во всех 416 формах корпуса
  поле 9 идёт подряд с 4152 в порядке записей.
- **Координаты — единицы диалога шрифта формы:** около 1,5 px по x и 1,625 px
  по y (MS Sans Serif 8), отсчёт от внешнего края окна с заголовком: смещение
  около (−6; −24) px. Клиентская область в единицах формы — примерно
  [4, W − 3] × [15, H − 3].
- Форма — MDI-окно класса `Afx:…` с заголовком формы, внутри `#32770`; кнопки —
  стандартный `Button`, надписи — `Static`, поля — `1CEDIT` (на 2 px больше
  расчётного размера).
- **Главное окно 1С в OLE-сеансе скрыто:** окна формы существуют, но невидимы;
  `PrintWindow` даёт однотонный снимок. Видимость кнопки подтверждена вручную (F2m).
- **Задача 010:** у окон формы и диалога свой `WS_VISIBLE` есть, скрыто только
  главное окно. `ShowWindowAsync(SW_SHOWNOACTIVATE)` показывает его за ~0,1 с,
  `SW_HIDE` возвращает стиль. После показа `PW_RENDERFULLCONTENT` даёт изображение
  формы из любого потока, флаг 0 — только из потока на desktop сеанса. Рамка окна —
  без DWM (desktop не входной). Повторы различаются только мигающим курсором
  (1×13 px); его прямоугольник даёт `GetGUIThreadInfo`, но лишь из потока на desktop
  сеанса (из другого — `ERROR_ACCESS_DENIED`, V1a). Снимок неизменённой формы
  повторяется байт в байт между запусками. После `BM_CLICK` фокус переходит
  на кнопку, курсор исчезает.
- `BM_CLICK` невидимой кнопке своего процесса на своём desktop вызывает
  обработчик формулы ровно один раз; сообщение возвращается за ~0,02 с.
- **Задача 011:** окна новых элементов — рамка и флажок `Button`, надпись
  `Static`, число и дата `BMASKED`, строка `1CEDIT`. `1CEDIT` — обёртка: текст,
  фокус и курсор — во вложенном окне `1CEDITSPR` (ID 0); `WM_CHAR` обёртке ничего
  не меняет (E1a), вложенному окну — вводит текст, и после `BM_CLICK` другому
  элементу значение доходит до модуля. Начальный фокус — у последней записи.
  Строка фиксированной длины возвращается с пробелами до длины, длину
  ограничивает само поле при вводе. Флажок отражает реквизит (`BM_GETCHECK`),
  `BM_CLICK` переключает его и вызывает формулу. 1С компилирует модуль с `Перем`,
  совпадающим с реквизитом формы, и переменная перекрывает реквизит (E4, E4b).
- **Задача 012:** ERT несёт свою копию метаданных — поток `Main MetaData Stream`
  (текст и байт NUL), и вид поля формы 1С ищет в ней: с пустой копией FIO.ERT
  («Задача») поле вида даёт «Ошибка создания внешнего отчета», поле «любой» —
  нет (R1, R1a, по одному полю); копия ERT корпуса или полные метаданные базы
  в FIO.ERT снимают ошибку (R1b, R1c). Поля показывают представление значения
  (счёт — код по маске плана счетов «51 .  . », без кнопки «…»); поле вида
  превращает значение другого вида в пустое значение своего (R3).
- **Задача 013:** номер поля вида 1С переводит в имя по копии ERT и ищет вид
  по имени в открытой базе: «Тарифы» под 25507 в копии стали «Тарифами» базы, где
  у них 26051 (K1, K2); после замены копии и перевода номера — тоже (K3). Номер,
  которого нет в непустой копии, отчёт не ломает, а делает поле «любым» (K5:
  `Справочник|`, K5b: поле держит элемент «Сотрудники»); с пустой копией (012) —
  «Ошибка создания внешнего отчета». `Документ.Выписка` (поле документа с видом)
  получает свой вид. У `Договор_Оргтехники.ert` три окна `BMASKED` расходятся
  с одним линейным отображением единиц на 1,9–2,3 px — больше допуска 2 px
  проверки раскладки `open`, поэтому пробы K объявляют `check`.
- **Задача 025:** `WM_NEXTDLGCTL(<окно>, TRUE)` диалогу формы переводит фокус во вложенное
  окно редактора поля (`1CEDITSPR`, ID 0). Значение доходит до реквизита только после ухода
  фокуса из поля: окно показывает введённый текст, а `Строка(Контекст.Код)` до этого пустая.
  `WM_NEXTDLGCTL(0, 0)` фокус из редактора не выводит: редактор — внук диалога.
  `GetNextDlgTabItem` возвращает само поле. Поэтому выход — `WM_NEXTDLGCTL` к следующему
  элементу описания. Сообщения 1С `MessageView.SaveToFile` пишет текстом, пометка важности
  «!» не сохраняется. Ошибка исполнения в обработчике кнопки — строка исходника и
  `{Справочник.Банки.Форма.Модуль(18)}: Деление на 0`. После закрытия формы кнопкой
  `#Записать Закрыть` вызов `Контекст.Форма.Закрыть(0)` даёт «Значение не представляет
  агрегатный объект (Форма)». Реквизиты формы и объекта читаются через контекст
  (`Контекст.Код`); отсутствующий реквизит перехватывается `Попытка`. `Форма.<Элемент>.Доступность(0)`
  снимает `IsWindowEnabled`, `Видимость(0)` — собственный `WS_VISIBLE`. Один вызов 1С после
  шага — 0,08–0,35 с.
- **Задача 026:** `Предупреждение`, `Вопрос` и вопрос самой 1С «Сохранить изменения?» — окна
  `#32770` с заголовком «1С:Предприятие», текстом в `Static` 65535 и стандартными ID кнопок:
  «OK» латиницей — 2, «&Да» — 6, «&Нет» — 7, «Отмена» — 2. `ВвестиСтроку`, `ВвестиЧисло`,
  `ВвестиДату` — `#32770` с подсказкой в заголовке, полем `1CEDIT`/`BMASKED` (ID 4146) с вложенным
  `1CEDITSPR`, кнопками «OK» (1), «Отмена» (2), «Помощь» (57670) и рамкой `BS_GROUPBOX`. Окно пустой
  даты сразу показывает текущую дату. Владелец модального окна выключен. Окно появляется через
  0,05–0,06 с после `BM_CLICK`, действие возвращается через 0,02–0,03 с после `WM_COMMAND`
  от кнопки. `#Закрыть` возвращается сразу, вопрос о сохранении появляется позже, во время
  следующего вызова 1С: вызов обслуживается в цикле окна.
- В 7.7 сравнения вокруг `ИЛИ` нужно брать в скобки: без них контроллер
  не компилируется («Неправильное использование арифметической или строковой
  операции»). Переменные модуля (`Перем`) в `ВыполняемыйМодуль` допустимы.

## Воспроизведение

```powershell
python -B -m unittest discover -s research/forms/tests
python -B research/forms/verify_corpus77.py .local/bases/base-for-test/ExtForms --output .artifacts/forms/corpus-NEW
python -B research/forms/prepare_cases77.py --stand .local/stage4-native/stand-native.toml --output .local/stage8-native/NEW
python -m harness77 run --project .local/stage8-native/NEW/f2.toml --stand .local/stage8-native/NEW/stand.toml --output-root .artifacts/runs
```

Свидетельства запуска — `<run>/form/`: `description.json` (описание собранной
ERT), `form-window.json` (окна, геометрия, отображение, нажатие), снимки.

Визуальные пробы (задача 010):

```powershell
python -B research/forms/prepare_visual77.py --stand .local/stage8-native/r2/stand.toml --output .local/stage10-native/NEW
python -m harness77 run --project .local/stage10-native/NEW/v-button.toml --stand .local/stage10-native/NEW/stand.toml --output-root .artifacts/runs
python -m harness77 visual approve --project .local/stage10-native/NEW/v-button.toml --run .artifacts/runs/<run_id> --by "<кто>"
python -B research/forms/verify_visual77.py --runs .artifacts/runs --series .local/stage10-native/series --output .artifacts/forms/visual-acceptance-NEW.json
```

Ссылочные поля (задача 012):

```powershell
python -B research/forms/verify_corpus77.py .local/bases/base-for-test/ExtForms --metadata .local/bases/base-for-test/1Cv7.MD --output .artifacts/forms/corpus-NEW
python -B research/forms/prepare_references77.py --stand .local/stage11-native/series/stand.toml --output .local/stage12-native/NEW
python -m harness77 run --project .local/stage12-native/NEW/r-references.toml --stand .local/stage12-native/NEW/stand.toml --output-root .artifacts/runs
python -B research/forms/verify_references77.py --runs .artifacts/runs --series .local/stage12-native/series `
  --corpus .artifacts/forms/corpus-20261019-v3 --corpus-md .artifacts/forms/corpus-20261019-v3-md `
  --output .artifacts/forms/references-acceptance-NEW.json
```

Сверка видов по именам (задача 013; `--foreign` — `1Cv7.MD` другой конфигурации,
только чтение):

```powershell
python -B research/forms/verify_corpus77.py .local/bases/base-for-test/ExtForms --metadata <другая база>/1Cv7.MD --output .artifacts/forms/corpus-NEW
python -B research/forms/prepare_kinds77.py --stand .local/stage12-native/series/stand.toml --foreign <другая база>/1Cv7.MD --output .local/stage13-native/NEW
python -m harness77 run --project .local/stage13-native/NEW/k3-replaced.toml --stand .local/stage13-native/NEW/stand.toml --output-root .artifacts/runs
python -B research/forms/verify_kinds77.py --runs .artifacts/runs --series .local/stage13-native `
  --corpus .artifacts/forms/corpus-20261019-013 --corpus-md .artifacts/forms/corpus-20261019-013-md `
  --corpus-foreign .artifacts/forms/corpus-20261019-013-ts --output .artifacts/forms/kinds-acceptance-NEW.json
```

Новые элементы (задача 011):

```powershell
python -B research/forms/prepare_elements77.py --stand .local/stage10-native/series/stand.toml --output .local/stage11-native/NEW
python -m harness77 run --project .local/stage11-native/NEW/e-elements.toml --stand .local/stage11-native/NEW/stand.toml --output-root .artifacts/runs
python -B research/forms/verify_elements77.py --runs .artifacts/runs --series .local/stage11-native/series --output .artifacts/forms/elements-acceptance-NEW.json
```

Формы `1Cv7.MD` (задача 022; профиль стенда задачи 021 с `copy_path`; эталоны визуальных случаев —
вне каталога серии):

```powershell
python -B research/forms/probe_md_forms77.py --stand .local/stage21-native/stand.toml --work .local/stage22-native/NEW `
  --evidence .artifacts/stage22-md-forms-YYYYMMDD-N.json [--case f-doc ...] [--baselines .local/stage22-native/baselines]
python -m harness77 visual approve --project .local/stage22-native/NEW/cases/v-first/project.toml `
  --run .artifacts/runs/<run_id> --by "<кто>"
```

Тестовые данные и существующие объекты (задача 024):

```powershell
python -B research/forms/probe_test_data77.py --stand .local/stage21-native/stand.toml --work .local/stage24-native/NEW `
  --evidence .artifacts/stage24-test-data-YYYYMMDD-N.json
```

`--case` выбирает отдельный случай; `--dry-run` только готовит исходники и собирает MD.
Подготовка выполняется один раз в копии; существующий объект открывается по возвращённой
ссылке, в режиме `owner` возвращается владелец нового подчинённого элемента. `verify` после
закрытия формы читает записанное значение. Ошибки подготовки и несовместимые ссылки не
открывают форму. Случаи и ожидания — в [задании](../../docs/tasks/024-test-data.md),
короткий пример — в [examples/test-data](../../examples/test-data/README.md).

Сценарии шагов (задача 025; профиль стенда задачи 021, каждый случай — на копии базы):

```powershell
python -B research/forms/probe_scenario77.py --stand .local/stage21-native/stand.toml --work .local/stage25-native/NEW `
  --evidence .artifacts/stage25-form-steps-YYYYMMDD-N.json [--case s-ok ...] [--dry-run]
python -B scripts/verify_form_steps77.py --evidence .artifacts/stage25-form-steps-YYYYMMDD-1.json `
  --example-run <run_id> --example-run <run_id> --regression 024=<run_id> --regression 022=<run_id> `
  --regression 023=<run_id> --output .artifacts/stage25-acceptance-NEW.json
```

Случаи и ожидания — в [задании](../../docs/tasks/025-form-steps.md), сценарий на неизменённой
форме — в [examples/form-steps](../../examples/form-steps/README.md).

Модальные окна в шагах (задача 026; профиль стенда задачи 021, каждый случай — на копии базы):

```powershell
python -B research/forms/probe_modal77.py --stand .local/stage21-native/stand.toml --work .local/stage26-native/NEW `
  --evidence .artifacts/stage26-modal-dialogs-YYYYMMDD-N.json [--case m-save ...] [--dry-run]
python -B scripts/verify_modal_dialogs77.py --evidence .artifacts/stage26-modal-dialogs-YYYYMMDD-1.json `
  --example-run <run_id> --example-run <run_id> --regression 025=<run_id> --regression 024=<run_id> `
  --regression 022=<run_id> --output .artifacts/stage26-acceptance-NEW.json
```

Случаи и ожидания — в [задании](../../docs/tasks/026-modal-dialogs.md), вопрос 1С на неизменённой
форме — в [examples/modal-dialogs](../../examples/modal-dialogs/README.md).
