# Публикация 0.9.0 и проверка файловых fixture/reader из опубликованного wheel

Поручение владельца — 14 ноября 2026 года, после приёмки 102.
Статус — **0.9.0 опубликована; полный цикл через скачанный wheel проверен**.
Приёмка повторной проверки владельцем отдельная.

## Итог повторной проверки

**26 нативных запусков и 21 отрицательная проверка — все ожидаемые исходы
подтверждены.** Основной цикл через run, CLI suite и stdio MCP:
passed / failed / passed / passed для исходника / ошибки +1 / исправления /
повтора. Регрессия даёт прежние четыре JSON-расхождения 90→91 и 140→141;
исправленный MD побайтно равен исходному. Тесты неизменны, SHA-256 scenario.json
`ae236a56c85ecf5a3150b49b17e4f8241aa8a4a20ea41925214eaa13d2fcd218`.

Встроенный вариант схемы 2 из 101 дополнительно прошёл через все три
интерфейса. В каждой основной suite 4 passed, 1 failed, 0 blocked, 0 skipped;
общий failed/1 ожидаем из-за прикладной регрессии. JSON/JUnit согласованы.
Два отдельных контроля неверной подписи первого открытия и reopen дали failed
именно в ожидаемых UI-проверках при правильных сохранённых данных.

Девять запусков правок файлов дали failed / failed / passed через каждый
интерфейс. Fixture меняет только комментарий — одно расхождение /comment_ok;
reader с {} — восемь missing_field; восстановление — passed. Использован
тот же профиль, его SHA-256 не изменился. Повторного project-init нет,
project.toml и scenario.json не переписываются. Исходные файлы восстановлены.

Семь отрицательных входов через каждый интерфейс дали 21 blocked до 1С:
отсутствующий файл, inline/file конфликт, не-UTF-8, непредставимый символ,
пустой файл, схема 2 с файловыми полями, каталог вместо файла. У suite нет
дочернего run и platform_checked=false. Тот же живой MCP затем выполнил
все три пробы правок/восстановления. Ping прошёл; оба MCP завершились с кодом 0.

Независимый verifier перечитал все 26 запусков — passed. Все прикладные
raw JSON, MD и диагностика совпали с принятой 102, включая правки файлов
и контроли подписи. Встроенная 101 совпала по raw JSON и MD с исходным
вариантом опубликованной 0.8.0. Все 46 снимков 23 файловых запусков совпали
с метаданными и телами фактически запущенных контроллеров; три встроенных
запуска не создают fixture-inputs. Прямое открытие/reopen и «Печать» проверены,
кода и артефактов журнала нет.

Источник, реестр и список процессов совпали до/после; копия и lock очищены,
forced_cleanup=false. Чужих активных 1С-сеансов в начальном снимке не было:
конкурентная работа с таким сеансом в этой серии не проверялась.
Повторный prepare выбрал cache; версия/хеш/Python и mtime wheel/Python
не изменились, скачивание и переустановка не понадобились.

- [Сводка](../../.artifacts/s102-published-evidence/summary.json),
  [полный протокол](../../.artifacts/s102-published-evidence/verified.json),
  [независимая проверка](../../.artifacts/s102-published-evidence/independent.json).
- [Сравнение с принятой 102](../../.artifacts/s102-published-evidence/accepted-102-comparison.json),
  [совместимость со встроенной 101](../../.artifacts/s102-published-evidence/inline-101-comparison.json),
  [сверка снимков и профилей](../../.artifacts/s102-published-evidence/snapshot-audit.json),
  [прямое открытие без журнала](../../.artifacts/s102-published-evidence/direct-opening-audit.json).
- [JUnit CLI](../../.artifacts/s102-published-evidence/reports/cli-suite/cycle/junit.xml),
  [JUnit MCP](../../.artifacts/s102-published-evidence/reports/mcp-suite/cycle/junit.xml),
  [кеш без переустановки](../../.artifacts/s102-published-evidence/cache-reuse.json),
  [архив проверенного проекта](../../.artifacts/s102-published-evidence/invoice-project.zip).

## Опубликованная поставка

[GitHub Release v0.9.0](https://github.com/AlexanderYekat/1cv7-harness/releases/tag/v0.9.0)
соответствует исходному коммиту `a82d1c78e60eef522bef7c44e9b53e2bcd81a80c`.
Аннотированный тег v0.9.0 опубликован на этом коммите; draft=false,
prerelease=false. Файлы:

- [Wheel](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.9.0/harness77-0.9.0-py3-none-any.whl),
  416214 байт, SHA-256
  `764354bbf8e7d1cd7ccbadb7a7f8e897158f106518003e887b7e927aa6847fd6`.
- [sdist](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.9.0/harness77-0.9.0.tar.gz),
  SHA-256 `507d37c5daebf575efb1007670c074f3397f06a8171a7de6f2dca91eeebe0e56`.
- [SHA256SUMS.txt](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.9.0/SHA256SUMS.txt).

GitHub API подтвердил digest загруженных файлов. Сборка получена из git archive
исходного коммита, wheel построен из sdist. 72 Python-файла и ресурса совпали
с принятой 102 после нормализации переводов строк; все 41 файл тестового
корпуса также совпали. Сгенерированный native manifest проверен отдельно:
его хеши соответствуют реальным байтам всех 33 файлов каждой поставки.
SHA-256 wheel отличается от первоначального локального wheel 102:
поставка пересобрана из зафиксированного дерева Git с актуальной документацией.
Нативная серия выше использует именно опубликованные и скачанные байты.

625 тестов установленного релизного wheel — **OK, skipped=5**; console lint,
compiler-protocol P1=60/P2=7 и инспекция всех 33 нативных файлов прошли.
Первая полная локальная попытка получила один WinError 5 при rename в прежнем
test_corrupt_cache_receipt_is_not_ready; этот отказ сохранён. Тот же wheel
и неизменные тесты полностью прошли повтор с системным TEMP.

[CI исходного коммита](https://github.com/AlexanderYekat/1cv7-harness/actions/runs/43560835243)
— success: Windows Python 3.11/3.13/3.15, Linux Python 3.13,
package Python 3.13 и обязательный ci.

[Итог локальной квалификации](../../.artifacts/s102-release-package/qualified.json),
[успешный полный лог](../../.artifacts/s102-release-package/installed-tests-system-temp.log),
[первая попытка и сборка](../../.artifacts/s102-release-package/summary.json),
[сверка с принятой 102](../../.artifacts/s102-release/build-identity.json),
[метаданные GitHub](../../.artifacts/s102-release/github-release.json),
[идентичность опубликованного тега](../../.artifacts/s102-release/tag-identity.json),
[сохранённый CI](../../.artifacts/s102-release/ci-source.json).

## Получение в новом проекте

Проект полной повторной серии — `C:/MyProjects/h77-102-published-final/`,
результаты — `C:/MyProjects/h77-102-published-cycle/`. В настройках connect
только version/URL/SHA-256; external-python и bundled_wheel отсутствуют.
До первого prepare нет cache и packages, маркер harness77.txt пустой,
локальное правило присутствует. Начальное acquisition.json подтвердило
source=download, ready=true, enabled=true, launch_performed=false.
Скачанный wheel имеет тот же SHA-256, что GitHub asset и SHA256SUMS.txt;
изолированная установка — `.harness77/cache/0.9.0-764354bbf8e7d1cd/`.

Профиль project.toml, scenario.json, контроллер и ERT побайтно совпали
с принятой 102. Fixture/reader/steps/expected и скрипты проверки из дерева
Git равны после нормализации переводов строк. Bootstrap для подготовки —
`.artifacts/s102-release-package/venv/Scripts/python.exe`; все операции
серии идут через локальный launcher и Python из acquisition.json.

[До первого prepare](../../.artifacts/s102-published-evidence/before-prepare.json),
[получение и сравнение входов](../../.artifacts/s102-published-evidence/acquisition-proof.json).

Предварительная попытка в h77-102-published успешно скачала wheel, но
вспомогательный аудит не распознал строку команды Windows и не записал
состояние до prepare. [Этот отказ обёртки сохранён](../../.artifacts/s102-release/first-preparation-audit.json);
каталог не использовался для нативной серии. Полная проверка начата в новом
h77-102-published-final с исправленным аудитом; код продукта и тесты не менялись.

## Воспроизведение

В команде подготовки примера используйте `--direct --file-fixtures`
и вместо `--wheel …`:

```powershell
--url https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.9.0/harness77-0.9.0-py3-none-any.whl --version 0.9.0 --sha256 764354bbf8e7d1cd7ccbadb7a7f8e897158f106518003e887b7e927aa6847fd6
```

Выбирайте новый проект/output. Остальные явные входы и команды run/verifier —
по [примеру](../../examples/invoice-project/README.md).

## Заданный объём

Зафиксировать принятую 102, собрать sdist и wheel из дерева этого коммита,
проверить установленную поставку и CI. Опубликовать GitHub Release v0.9.0
с wheel, sdist и SHA256SUMS.txt.

Создать новый прикладной проект вне checkout через опубликованный URL,
version/SHA-256 и harness77.txt. До первого prepare нет bundled wheel,
external-python или прежнего кеша; подтвердить реальное source=download,
хеш asset и изолированную установку. Повторный prepare должен использовать cache.

Повторить принятую 102 с неизменными тестами: исходник, ошибка +1,
исправление и повтор через run, CLI suite и stdio MCP; прямое открытие и
переоткрытие фактуры с динамической подписью «Печать». Отдельно проверить
контроли подписи, встроенные тексты 101 и правки fixture.1s/reader.1s при том
же профиле без повторного project-init. Сохранить снимки реально использованных
байтов, SHA-256, JSON/JUnit и ответы живого MCP, проверить отрицательные входы
и восстановление после них. Независимо сверить результаты с принятой 102,
сохранность исходной базы, реестра, процессов и очистку копий.

Квалификация остаётся прежней: Windows / 7.70.027 / квалифицированные
компоненты / DBF. Приёмка повторной проверки владельцем отдельная.

[Принятая 102](102-file-fixtures.md),
[первоначальная техническая проверка](102-file-fixtures-acceptance.md),
[команды проекта](../../examples/invoice-project/README.md).
