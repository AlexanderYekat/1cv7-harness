# Публикация 0.14.0 и проверка скачанной поставки

Поручение владельца — 16 ноября 2026 года, после приёмки задачи 107.
Статус — **0.14.0 опубликована, скачанный wheel проверен полными нативными сериями**.
Релиз и его проверка приняты владельцем 16 ноября 2026 года.
Релиз объединяет принятые [106](106-inspect-combo-acceptance.md)
и [107](107-create-combo-acceptance.md).

## Публикация и источник

[GitHub Release v0.14.0](https://github.com/AlexanderYekat/1cv7-harness/releases/tag/v0.14.0)
привязан аннотированным тегом к коммиту
`c614e2a68752fa824ebedf7c50692cd01e4062cc`. Тег и объект commit проверены
через GitHub API, draft=false, prerelease=false.

Опубликованы ровно три файла:

- [harness77-0.14.0-py3-none-any.whl](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.14.0/harness77-0.14.0-py3-none-any.whl),
  422260 байт, SHA-256 `e859c6d2abf3ea2864419a2512f27433263616353f5d1d7f4b44f9d666cbfed8`.
- [harness77-0.14.0.tar.gz](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.14.0/harness77-0.14.0.tar.gz),
  1146250 байт, SHA-256 `c2db007730da48de682aa3a95b9e2d85717ac45d77e1f4dda9947b8e4b2c5b8a`.
- [SHA256SUMS.txt](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.14.0/SHA256SUMS.txt),
  190 байт, SHA-256 `250caa3e4d18c881cd6e0d62ee6e0dda59036bbd31f75b2ea1822b7d35177f85`.

GitHub подтвердил размер и digest каждого asset. Все файлы скачаны заново
через `gh release download`: байты совпали с квалифицированной сборкой.
[Метаданные релиза](../../.artifacts/s107-release/github-release.json),
[тег](../../.artifacts/s107-release/tag-identity.json),
[сверка скачивания](../../.artifacts/s107-release/publication-verified.json).

## Сборка и переносимые проверки

Из `git archive` исходного коммита собран sdist, затем wheel из sdist.
73 файла пакета сверены с принятой разработческой сборкой 107: после
нормализации CRLF/LF отличается только версия в `__init__.py` и соответствующий
native manifest. Все 33 native-файла проверены по фактическим SHA-256.
Примеры 106–107 также сверены с принятыми исходниками после нормализации строк.
[Сверка](../../.artifacts/s107-release/build-identity.json).

638 тестов установленного wheel прошли, 5 skipped. Пакет проверен в чистом
окружении без сети, PYTHONPATH/PYTHONHOME и соседних репозиториев; lint и
compiler-protocol P1=60/P2=7 совпали с ожиданиями.
[Отчёт пакета](../../.artifacts/s107-release-package/summary.json),
[журнал](../../.artifacts/s107-release-package/installed-tests.log).
256 тестов runtime форм прошли локально.

[CI исходного коммита](https://github.com/AlexanderYekat/1cv7-harness/actions/runs/43805834575)
успешен: Windows Python 3.11/3.13/3.15, Linux Python 3.13, package и ci.
[Сохранённый CI](../../.artifacts/s107-release/ci-source.json).

## Нативная проверка скачанного wheel

Wheel из каталога скачивания подключён через `connect --bundle` в новый
проект `.artifacts/s107-release-native-106-project` и установлен в новый
cache версии 0.14.0 с закреплённым SHA-256. Все файлы установленного пакета
сверены побайтно с wheel. Нативные процессы используют эту установленную
поставку; PYTHONPATH/PYTHONHOME исключены. Stand использует bundled runtime
`forms`, а не исследовательский launcher из checkout.
[Получение пакета](../../.artifacts/s107-release-native-106-project/acquisition.json).

Полная серия включает **44 завершённых квалификационных запуска**:

- **106 — 18 запусков чтения и граничных состояний**: обычное чтение двух
  списков, дубликаты/пустой текст, пустой список, переполнение, восстановление
  после отказа и положительный контроль обработчика. Каждый случай выполнен
  через run, CLI suite и MCP; переполнение даёт ожидаемый failed.
  Независимо перечитаны 18 отчётов, 30 snapshots COMBOBOX и 72 снимка входов.
- **106 — 12 запусков прикладного цикла** baseline/regression/fixed/repeat-fixed:
  passed/failed/passed/passed через каждый из run, CLI suite и MCP. Тексты для
  select получены из discovery. Запись/reopen и независимый reader подтверждают
  ТипУслуги=2; при внесённой ошибке reader даёт ровно одно расхождение
  `/service_type`: expected=2, actual=1. Четыре тестовых входа заморожены на
  весь цикл. Сверены 48 snapshots COMBOBOX, 24 состояния геометрии и
  216 отрицательных подмен измерений; максимум невязки — 1,01 px при допуске 2 px.
- **107 — 12 запусков создания COMBOBOX**: те же четыре фазы и три транспорта
  с ожидаемыми passed/failed/passed/passed. Описание формы и шаги побайтно
  одинаковы; regression увеличивает счётчик обработчика на 2 вместо 1.
  Исправление восстанавливает модуль побайтно. Входы form.json/steps.json/module.1s
  нового проекта совпали с принятой серией 107 побайтно.
  Перечитаны 21 snapshot, ERT-контейнеры и остальные потоки шаблона;
  snapshots между транспортами совпали. Максимум невязки геометрии — 0,48 px.
- **Совместимость 104–105 — два запуска** неизменённых принятых прикладных
  примеров. UI, JSON-ожидания и независимые reader прошли; четыре входа каждого
  примера сохранились побайтно.

В 44 завершённых запусках — 35 passed и 9 ожидаемых failed. Все 99 snapshots
COMBOBOX сверены по SHA-256 и обычным ссылкам result_files. JSON/JUnit
согласованы; suite продолжают выполнение после ожидаемого отказа. MCP
отвечает на ping во время и после suite, серверы завершаются с кодом 0.
Диагностика, результаты reader и канонические итоги 106 совпали с принятой
серией 0.13.0. Все 73 файла установленного пакета, включая 33 native-файла,
повторно сверены с байтами скачанного wheel в финальном аудите.

Во всех 44 завершённых запусках сеансы завершились штатно, без принудительной
очистки. База, реестр и чужие 1С-процессы до/после совпали; копия и lock удалены.

Свидетельства:

- [Чтение и граничные состояния 106](../../.artifacts/s107-release-native-106/verified.json),
  [независимая сверка](../../.artifacts/s107-release-native-106/read-verification.json).
- [Прикладной цикл 106](../../.artifacts/s107-release-native-106/cycle/verified.json),
  [геометрия и независимая сверка](../../.artifacts/s107-release-native-106/cycle/independent.json).
- [Цикл создания 107](../../.artifacts/s107-release-native-107/verified.json),
  [независимая сверка](../../.artifacts/s107-release-native-107/independent.json).
- [Совместимость 104–105](../../.artifacts/s107-release-compatibility-r2/verified.json).
- [Финальная квалификация поставки](../../.artifacts/s107-release/final-qualification.json).

## Отдельный отказ запуска и повтор

Всего было **45 попыток**, включая один дополнительный blocked при первом
запуске совместимости 104. До Initialize Windows вернул WinError 5 при
переименовании `native/startup.json.tmp` в `startup.json`; platform_checked=false.
Причина отказа самой операции Windows не установлена. Код, wheel и ожидания
после этого не менялись.

Принадлежавший этому запуску сеанс завершён принудительно; cleanup_verified=true
и others_preserved=true. Состояние базы, реестра и процессов перед повтором
совпало с исходным состоянием серии 106. Повтор в новом каталоге тем же wheel
успешно выполнил оба примера 104–105. Отказ не включён в 44 завершённых
квалификационных запуска и сохранён отдельно:
[run.json](../../.artifacts/s107-release-compatibility/104/bb4ed811-0cfb-463b-b7d0-abe730706aac/run.json),
[протокол платформы и очистки](../../.artifacts/s107-release-compatibility/104/bb4ed811-0cfb-463b-b7d0-abe730706aac/platform-result.json).

Релизные файлы и тег после публикации и проверки не заменялись.

Нативный охват ограничен прежним Windows/1С 7.70.027/DBF-стендом и закреплёнными
компонентами. Платформы и конфигурации за пределами этого стенда не квалифицированы.
