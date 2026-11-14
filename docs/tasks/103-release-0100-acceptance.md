# Публикация 0.10.0 и проверка файловых steps/expected из опубликованного wheel

Поручение владельца — 14 ноября 2026 года, после приёмки 103.
Статус — **0.10.0 опубликована; полный цикл через скачанный wheel проверен**.
Приёмка повторной проверки владельцем отдельная.

## Итог повторной проверки

Финальная полная серия — **38 нативных запусков и 54 отказа входов до 1С**,
все ожидаемые исходы подтверждены. Основной цикл через run, CLI suite и
stdio MCP дал passed / failed / passed / passed для исходника / ошибки +1 /
исправления / повтора. Регрессия обнаружена с четырьмя прежними JSON-различиями
90→91 и 140→141; исправленный MD побайтно равен исходному.

Встроенная 101 схемы 2 и файловая 102 схемы 3 прошли через все три интерфейса.
В каждой основной suite — 5 passed, 1 failed, 0 blocked, 0 skipped;
единственный failed — запланированная прикладная регрессия. JSON/JUnit
согласованы. Два отдельных контроля неверной подписи первого открытия и
reopen дали failed именно в ожидаемых UI-проверках при правильных данных.

Девять проб steps/expected дали failed / failed / passed у каждого
интерфейса. Правка steps действительно сохранила количество 4 и суммы
120/170, все 25 UI-шагов прошли; прежний expected дал пять различий,
включая /rows/1/quantity. Правка только expected.total 140→141 дала одно
расхождение 141/140 при правильном UI. Восстановление вернуло passed.
Тот же профиль сохранил SHA-256, повторного project-init и перегенерации нет.
Пробы fixture/reader из 102 также повторены; все четыре файла восстановлены.

21 неправильный вход fixture/reader и 33 JSON-входа отклонены до платформы,
у suite нет дочернего run. Те же живые MCP после отрицательных входов
выполнили правки/восстановление. Ping прошёл; все три MCP завершились
штатно с кодом 0. Профиль, scenario.json и бизнес-тесты неизменны;
SHA-256 scenario.json —
`11d425f0bb98cffbabf2677e79380f0799cb29704f628d954839698835597e59`.

Независимый verifier перечитал 38 запусков — passed. Все raw JSON, MD
и диагностика, включая правки файлов и контроли подписи, совпали с принятой
103. Совместимые 101–102 совпали по raw JSON и MD с исходным вариантом
опубликованной 0.9.0. Все 134 снимка сверены: 70 fixture/reader в 35 запусках
и 64 JSON-входа в 32 запусках. Тела fixture/reader найдены в фактических
контроллерах; каждый JSON-шаг сопоставлен с нативным планом по индексу,
операции, цели и исходным параметрам; expected совпал с эффективными тестами.
Прямое открытие/reopen и «Печать» подтверждены; кода и артефактов журнала нет.

Источник, реестр и список процессов совпали до/после, копия и lock очищены,
forced_cleanup=false. Начальный список чужих 1С-сеансов был пуст: совместная
работа с активным чужим сеансом этой серией не подтверждается.
Повторный prepare выбрал cache; версия, SHA-256, Python и mtime wheel/Python
те же, скачивание и переустановка не понадобились.

- [Сводка](../../.artifacts/s103-published-evidence/summary.json),
  [полный протокол](../../.artifacts/s103-published-evidence/verified.json),
  [независимая проверка](../../.artifacts/s103-published-evidence/independent.json).
- [Сравнение с принятой 103](../../.artifacts/s103-published-evidence/accepted-103-comparison.json),
  [совместимость 101–102](../../.artifacts/s103-published-evidence/compatibility-101-102.json),
  [снимки, планы и профили](../../.artifacts/s103-published-evidence/snapshot-audit.json),
  [прямое открытие](../../.artifacts/s103-published-evidence/direct-opening-audit.json).
- [JUnit CLI](../../.artifacts/s103-published-evidence/reports/cli-suite/cycle/junit.xml),
  [JUnit MCP](../../.artifacts/s103-published-evidence/reports/mcp-suite/cycle/junit.xml),
  [кеш без переустановки](../../.artifacts/s103-published-evidence/cache-reuse.json).
- [Архив проверенного проекта](../../.artifacts/s103-published-evidence/invoice-project.zip),
  37 файлов, SHA-256 `3e0687036002efa39462fd1571a6a7e01978b84d1ea6a6294b7ad71a5c4e79ad`.

## Опубликованная поставка

[GitHub Release v0.10.0](https://github.com/AlexanderYekat/1cv7-harness/releases/tag/v0.10.0)
соответствует исходному коммиту `377385e9f3298c0323e07de9489f88672e490760`.
Опубликованный аннотированный тег сверен с ним; draft=false, prerelease=false.
Файлы релиза:

- [Wheel](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.10.0/harness77-0.10.0-py3-none-any.whl),
  417701 байт, SHA-256
  `24ba9a9b5ef2fc3957a417f56aaf19e683329b11c57c02ec7924766764a84aa2`.
- [sdist](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.10.0/harness77-0.10.0.tar.gz),
  SHA-256 `ab20d58cacf98d26ae00d9b945ac9da9204dee8193c3abf1668435a90fe7e7fc`.
- [SHA256SUMS.txt](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.10.0/SHA256SUMS.txt).

GitHub API подтвердил digest всех трёх файлов. Сборка получена из git archive
исходного коммита, wheel построен из sdist. 72 файла кода/ресурсов совпали
с принятой 103 после нормализации переводов строк; все 42 файла тестового
корпуса также совпали. Сгенерированные native manifest проверены отдельно:
их хеши соответствуют реальным байтам всех 33 файлов каждой поставки.
SHA-256 wheel отличается от первоначального локального wheel 103:
поставка пересобрана из зафиксированного дерева Git с актуальной документацией.
Финальная нативная серия использует именно опубликованные и скачанные байты.

Полный verifier установленной релизной поставки — **passed**:
635 тестов — OK, skipped=5; console lint, compiler-protocol P1=60/P2=7,
точный состав и SHA-256 нативного payload проверены. Тестовый корпус неизменен.

[CI исходного коммита](https://github.com/AlexanderYekat/1cv7-harness/actions/runs/43572244055)
— success: Windows Python 3.11/3.13/3.15, Linux Python 3.13,
package Python 3.13 и обязательный ci.

[Проверка поставки](../../.artifacts/s103-release-package/summary.json),
[лог всех тестов](../../.artifacts/s103-release-package/installed-tests.log),
[сверка с принятой 103](../../.artifacts/s103-release/build-identity.json),
[метаданные GitHub](../../.artifacts/s103-release/github-release.json),
[тег и исходный коммит](../../.artifacts/s103-release/tag-identity.json),
[сохранённый CI](../../.artifacts/s103-release/ci-source.json).

## Получение в новом проекте

Проект — `C:/MyProjects/h77-103-published/`, результаты —
`C:/MyProjects/h77-103-published-final-cycle/`. В config.json только закреплённые
version/URL/SHA-256 и локальные привязки: нет external-python и bundled_wheel.
До первого prepare нет cache и packages; marker harness77.txt пустой,
локальное правило присутствует. Начальное acquisition.json подтвердило
source=download, ready=true, enabled=true, launch_performed=false.
Скачанный wheel имеет опубликованный SHA-256, изолированная установка —
`.harness77/cache/0.10.0-24ba9a9b5ef2fc39/`.

Профиль, scenario.json, контроллер и ERT побайтно совпали с принятой 103;
четыре входных файла и скрипты из дерева Git равны после нормализации
переводов строк. Bootstrap — `.artifacts/s103-release-package/venv/Scripts/python.exe`;
операции серии используют локальный launcher и Python из acquisition.json,
с пустыми PYTHONPATH/PYTHONHOME и отключённым user site.

[До первого prepare](../../.artifacts/s103-published-evidence/before-prepare.json),
[получение и сравнение входов](../../.artifacts/s103-published-evidence/acquisition-proof.json).

Первый нативный исходный запуск в h77-103-published-cycle дал failed:
на шаге 2 переключение вкладки не получило ответ 1С за 30 секунд, поэтому
reader увидел начальные 80 вместо 140. Этот запуск не объявляется успешным
и [сохранён отдельно](../../.artifacts/s103-published-evidence/initial-native-failure.json).
Платформа завершилась штатно, forced_cleanup=false; источник, реестр,
процессы, входы проекта и очистка копии независимо проверены. Повторная
полная серия прошла на том же проекте, wheel, тестах и сроках,
без перегенерации, в новом каталоге h77-103-published-final-cycle.

## Воспроизведение

В команде подготовки примера используйте `--direct --file-fixtures --json-files`
и вместо `--wheel …`:

```powershell
--url https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.10.0/harness77-0.10.0-py3-none-any.whl --version 0.10.0 --sha256 24ba9a9b5ef2fc3957a417f56aaf19e683329b11c57c02ec7924766764a84aa2
```

Выбирайте новые проект/output. Остальные явные входы и команды — по
[примеру](../../examples/invoice-project/README.md).

## Заданный объём повторной проверки

Зафиксировать принятую 103, собрать sdist и wheel из дерева коммита,
проверить установленную поставку и CI. Опубликовать GitHub Release v0.10.0
с wheel, sdist и SHA256SUMS.txt.

Создать новый прикладной проект вне checkout через опубликованный URL,
version/SHA-256 и harness77.txt. До первого prepare нет local/bundled wheel,
external-python и кеша; подтвердить source=download, SHA-256 asset и
изолированную установку. Повторный prepare должен использовать cache.

Повторить принятую 103 с неизменными тестами: исходник, ошибка +1,
исправление и повтор через run, CLI suite и stdio MCP. Дополнительно —
встроенная 101, файловая 102, контроли подписи, правки fixture/reader,
правки steps/expected и восстановление при том же профиле без project-init.
Ожидаются 38 нативных запусков и 54 отказа входов до платформы; живые MCP
после отрицательных входов выполняют корректные запросы и штатно завершаются.

Независимо сверить результаты с принятой 103, raw JSON/MD/диагностику,
JSON/JUnit, точные снимки файлов и нативные планы шагов. Проверить сохранность
исходной базы, реестра, процессов и очистку копий. Квалификация ограничена
прежним стендом Windows / 7.70.027 / квалифицированные компоненты / DBF.

[Принятая 103](103-file-json-inputs.md),
[исходная проверка](103-file-json-inputs-acceptance.md),
[команды](../../examples/invoice-project/README.md).
