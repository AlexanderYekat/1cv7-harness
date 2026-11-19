# Выпуск 0.17.0 и проверка скачанного wheel

0.17.0 опубликована 19 ноября 2026 года. Аннотированный тег относится к
принятому коммиту `c9a76e0d6eed471e7e2da82af389930dc540c719`. CI этого коммита
прошёл до выпуска на Windows с Python 3.11, 3.13 и 3.15 и на Linux с Python
3.13. Временная ветка CI удалена.
[Релиз](https://github.com/AlexanderYekat/1cv7-harness/releases/tag/v0.17.0),
[CI](https://github.com/AlexanderYekat/1cv7-harness/actions/runs/44521044500).

Из `git archive` собран sdist, затем wheel. Установленный пакет прошёл 649
тестов с 5 пропусками. Файлы пакета совпали с принятой сборкой после
нормализации переводов строк. Все 33 нативных файла сверены с манифестом.
[Проверка пакета](../../.artifacts/s113-release/package/summary.json),
[сверка сборок](../../.artifacts/s113-release/build-identity.json).

Wheel, sdist и `SHA256SUMS.txt` скачаны с GitHub. Их байты, размеры и SHA-256
совпали с релизной сборкой и метаданными. SHA-256 wheel
`92a745c48f467424465f8894cfbac52cd353ba4c7bfdc4ae07e9c8ff86cdaa09`.
[Сверка скачивания](../../.artifacts/s113-release/publication-verified.json).

Скачанный wheel установлен в `C:/MyProjects/h77-0170-download` без сети и
зависимостей. Все 76 файлов установки совпали с wheel. На штатном стенде
Windows / 1С 7.70.027 / DBF оба проекта прошли цикл `project-init → run`.
Услуги использовали встроенный рецепт, счёт-фактура — пользовательский TOML,
перенесённый после подготовки. `project.toml` и сгенерированные входы
сохранили SHA-256. Прошли все 19 и 25 UI-шагов соответственно, reader
в обоих случаях получил ожидаемый JSON. База, реестр и чужие процессы
сохранены. Копия и lock удалены.
[Нативный отчёт](../../.artifacts/s113-release/native-verification.json).
