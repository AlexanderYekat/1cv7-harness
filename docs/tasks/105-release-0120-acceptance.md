# Публикация 0.12.0 и проверка скачанной поставки

Поручение владельца — 16 ноября 2026 года, после приёмки задачи 105.
Статус — **0.12.0 опубликована и проверена на скачанном релизном wheel**.
Основной цикл и дополнительные нативные проверки завершены.
Основа — [принятая 105](105-combo-selection-acceptance.md).

## Опубликованные файлы

[GitHub Release v0.12.0](https://github.com/AlexanderYekat/1cv7-harness/releases/tag/v0.12.0)
привязан аннотированным тегом к исходному коммиту
`7fc3b779c974dd1be34bcbeef0f736ed4d3f34fc`. Тег проверен по GitHub API;
draft=false, prerelease=false. Опубликованы ровно три файла:

- [harness77-0.12.0-py3-none-any.whl](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.12.0/harness77-0.12.0-py3-none-any.whl),
  420765 байт, SHA-256 `22764b6e1b3d05813ea11a549b307bb1bc12996dcf4dff1dcaa75dd51e705a3c`.
- [harness77-0.12.0.tar.gz](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.12.0/harness77-0.12.0.tar.gz),
  1131679 байт, SHA-256 `aeebb5d41683da543d910098b0a350a2228d0f6a636196d3bccb00e24b135e48`.
- [SHA256SUMS.txt](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.12.0/SHA256SUMS.txt),
  190 байт, SHA-256 `75921a85c1d00072a0f03a8f0a75d297570152973b366a35c04956e1e11d608b`.

GitHub подтвердил digest и размер каждого asset. После публикации все три
файла скачаны заново через `gh release download`; байты и SHA-256 совпали
с квалифицированной сборкой. Нативный проект использует именно wheel из
каталога скачивания, скопированный в новый локальный bundle и установленный
в новый cache с этим SHA-256.
[Метаданные релиза](../../.artifacts/s105-release/github-release.json),
[тег](../../.artifacts/s105-release/tag-identity.json),
[проверка скачивания](../../.artifacts/s105-release/publication-verified.json).

## Сборка и проверки пакета

Сборка из `git archive` исходного коммита: сначала sdist, затем wheel из
sdist. 72 файла кода/ресурсов совпали с принятой локальной 0.12.0 после
нормализации CRLF/LF, оба native manifest проверены по фактическим байтам.
42 файла тестового корпуса также совпали после нормализации переводов строк.
Логика runtime не менялась. Четыре прикладных входа fixture/reader/steps/expected
в новом проекте совпали с принятой серией побайтно; это проверено
оркестратором перед первым запуском. Документация в metadata и нормализация
переводов строк Git объясняют отличие SHA-256 от принятой локальной сборки.
[Сверка поставок](../../.artifacts/s105-release/build-identity.json).

635 тестов установленного релизного wheel прошли, 5 skipped, без повторов.
CLI lint и compiler-protocol P1=60/P2=7 прошли. Проверка выполнена вне checkout,
без PYTHONPATH/PYTHONHOME и sibling repositories.
[Квалификация](../../.artifacts/s105-release-package/summary.json),
[лог тестов](../../.artifacts/s105-release-package/installed-tests.log).

[CI исходного коммита](https://github.com/AlexanderYekat/1cv7-harness/actions/runs/43763289423)
— success: Windows Python 3.11/3.13/3.15, Linux Python 3.13, package и ci.
В исследовательский набор входят 250 тестов форм, включая 12 новых тестов 105.
[Сохранённые результаты CI](../../.artifacts/s105-release/ci-source.json).

## Нативный повтор

Проект: `.artifacts/s105-release-native-project`.
Основная серия: `.artifacts/s105-release-native-cycle`.
Дополнительные проверки: `.artifacts/s105-release-native-controls`.

Те же baseline/regression/fixed/repeat-fixed завершены через run, CLI suite
и stdio MCP: **12 ожидаемых нативных исходов**, passed/failed/passed/passed
в каждом транспорте. При внесённой ошибке после записи/reopen reader
показал ровно одно отличие `/service_type`: expected=2, actual=1.
Исправление и повтор прошли с прежними четырьмя тестовыми входами.

Оба suite продолжили работу после ожидаемого провала. MCP отвечал на ping
во время и после suite, сервер вышел с кодом 0. Независимый verifier подтвердил
равенство диагностик между транспортами, JSON/JUnit и 48 побайтных снимков
входов. Сверены 24 состояния геометрии, все 216 отрицательных подмен
измерений отклонены; максимальная невязка 1,01 px при допуске 2 px.
Источник, реестр и список процессов до/после совпали,
копия и lock очищены, принудительное завершение не требовалось.

[Проект и установленный SHA-256](../../.artifacts/s105-release-native-project/acquisition.json),
[основная серия](../../.artifacts/s105-release-native-cycle/verified.json),
[независимая сверка](../../.artifacts/s105-release-native-cycle/independent.json).

Дополнительные проверки выполнены тем же скачанным wheel:

- `missing`: ожидаемый отказ `0 matching items`, выбор и сохранённый ТипУслуги=1 не изменены.
- `duplicate`: ожидаемый отказ `2 matching items`, выбор и сохранённый ТипУслуги=1 не изменены.
- `modal`: dialog-шаг ответил на предупреждение обработчика; после записи/reopen
  reader подтвердил ТипУслуги=2. Все шаги прошли.

Итого **15 нативных запусков** — 12 основных и 3 дополнительных,
без неожиданных исходов. Структурированные итоги run и обоих suite совпали
с итогами принятой серии 105; четыре тестовых входа побайтно прежние.
Все 33 установленных native-файла сверены с файлами скачанного wheel и его
manifest. Исходная база, реестр и процессы сохранены, копия и lock убраны
после каждой дополнительной проверки; принудительное завершение не требовалось.

[Три дополнительных случая](../../.artifacts/s105-release-native-controls/verified.json),
[финальная квалификация](../../.artifacts/s105-release/final-qualification.json).

Нативная квалификация ограничена прежним Windows/1С 7.70.027/DBF-стендом,
с закреплёнными 1С++/FormEx и helper/identity. Чужих 1С-сеансов перед серией
не было. Публикация и последующая проверка выполнялись на одних и тех же
байтах; релизные файлы после проверки не заменялись.
