# Публикация 0.11.0 и проверка релизной поставки

Поручение владельца — 15 ноября 2026 года, после приёмки задачи 104.
Статус — **0.11.0 опубликована и проверена**. Основа — [принятая 104](104-services-project-acceptance.md).

## Опубликованная поставка

[GitHub Release v0.11.0](https://github.com/AlexanderYekat/1cv7-harness/releases/tag/v0.11.0) соответствует исходному коммиту
`45322c0b0979da31f70e8c3d0029383413a6b687`. Аннотированный тег проверен по GitHub API;
draft=false, prerelease=false. Загружены ровно три файла:

- [harness77-0.11.0-py3-none-any.whl](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.11.0/harness77-0.11.0-py3-none-any.whl), 419038 байт, SHA-256 `c25e27fd9dc6cadebc84224f2f2505d55f895771f1de95a8115c3d4fa740cd16`.
- [harness77-0.11.0.tar.gz](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.11.0/harness77-0.11.0.tar.gz), 1123573 байт, SHA-256 `bcaedad87ca3bf9f84e54198b96f4b98e5316ad719b2f0bacb1c0a45d888f3fd`.
- [SHA256SUMS.txt](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.11.0/SHA256SUMS.txt), 192 байт, SHA-256 `520def0c4d1ac9801a9c6870037e20a1d63ae3e661e9d13ebd70622e8f90daad`.

GitHub подтвердил digest и размер каждого файла. После публикации все три
файла скачаны заново; их SHA-256 совпали с локальными квалифицированными байтами.
[Метаданные GitHub](../../.artifacts/s104-release/github-release.json),
[тег](../../.artifacts/s104-release/tag-identity.json),
[проверка скачивания](../../.artifacts/s104-release/publication-verified.json).

## Сборка и проверка кода

Сборка выполнена из git archive исходного коммита: сначала sdist, затем wheel
из sdist. 72 файла кода/ресурсов и
43 файла тестового корпуса совпали с принятой
поставкой после нормализации CRLF/LF. Прикладные fixture/reader/steps/expected
и оба контроллера сверены отдельно; логика не менялась. Оба native manifest
проверены по фактическим байтам всех файлов. Документация и переводы строк
объясняют отличие SHA-256 от локального wheel принятой 104.
[Сверка поставок](../../.artifacts/s104-release/build-identity.json).

635 тестов установленного релизного wheel проверены, 5 skipped.
Три временных отказа Windows при rename получили успешный адресный повтор
без изменения пакета, тестов или их сроков. CLI lint и P1=60/P2=7 прошли.
[Квалификация пакета](../../.artifacts/s104-release-package/qualification-final.json),
[полный лог](../../.artifacts/s104-release-package/installed-tests.log),
[повтор трёх случаев](../../.artifacts/s104-release-package/installed-tests-retry.log).

[CI исходного коммита](https://github.com/AlexanderYekat/1cv7-harness/actions/runs/43740526106)
— success: Windows Python 3.11/3.13/3.15, Linux Python 3.13, package и ci.
238 тестов форм прошли также в CI. [Сохранённый результат](../../.artifacts/s104-release/ci-source.json).

## Нативная проверка релизных байтов

Именно релизный wheel прошёл **12 нативных запусков**: по четыре через run,
CLI suite и stdio MCP. В каждом транспорте baseline/regression/fixed/repeat-fixed
дали passed/failed/passed/passed. Искусственная ошибка +1 обнаружена после
записи/reopen: 91 вместо 90 и 141 вместо 140, ровно четыре JSON-различия.
Исправление и повтор прошли с теми же тестовыми входами.

Независимый verifier подтвердил 24 состояния геометрии,
максимум 1.01 px при допуске 2 px, 216
офлайн-подмен измерений, совпадение диагностик транспортов, JSON/JUnit и
48 точных снимков входов. MCP отвечал на ping во время/после suite и вышел с кодом 0.
Снимки источника, реестра и процессов до/после совпали; копия и lock очищены.
Начальный список чужих 1С-сеансов был пуст. Нативная квалификация ограничена
проверенным Windows/7.70.027/DBF-стендом с 1С++/FormEx и закреплёнными helper/identity.

[Полная серия](../../.artifacts/s104-release-native-cycle/verified.json),
[независимая сверка](../../.artifacts/s104-release-native-cycle/independent.json),
[поставка проекта](../../.artifacts/s104-release-native-project/acquisition.json).
Все эти запуски использовали байты с опубликованным SHA-256; последующее
скачивание подтвердило их идентичность.
