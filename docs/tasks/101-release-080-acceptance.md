# Публикация 0.8.0 и проверка опубликованного wheel

Поручение владельца — 13 ноября 2026 года, после приёмки 101.
Статус — **0.8.0 опубликована, полный цикл через скачанный wheel проверен**.

## Итог повторной проверки

14 нативных запусков из нового проекта — с ожидаемыми результатами.
Основной цикл: по четыре варианта через run, CLI suite и stdio MCP suite,
в каждом случае **passed / failed / passed / passed** для исходника /
контролируемой ошибки / исправления / повтора. У каждой suite 3 passed,
1 failed, 0 blocked, 0 skipped; общий failed/1 ожидаем из-за регрессии.
Два отдельных контроля неверной подписи первого открытия и reopen дали failed
именно в соответствующих UI-проверках при правильных сохранённых данных.

Независимый verifier перечитал все 14 запусков: **passed**. Тестовый
scenario.json тот же, что в принятой 101, SHA-256
`2b11946f40e02d05f232fce7ae74b6414e4e82134956bbd3bcb56129e9ae4e1e`.
Прикладные raw JSON, MD и диагностики совпали с первоначальной 101 через
все три интерфейса, включая отрицательные контроли. Исправленный MD побайтно
равен исходному. JSON/JUnit согласованы, MCP отвечал на ping во время
и после suite и штатно завершился с кодом 0.

Все контроллеры открывают фактуру прямо по Объект77Данных: кода и артефактов
журнала нет. Проверены «Печать» до правки и после reopen, исчезновение старых
окон и равенство сохранённой ссылки. Прочие подписи/геометрия проверяются.
Снимки источника, реестра и процессов совпали до/после; копия и lock очищены,
forced_cleanup=false. Чужих активных 1С-сеансов в начальном снимке не было;
конкурентная работа с таким сеансом отдельно не проверялась.

Повторный prepare выбрал **cache**: версия/хеш/Python те же, mtime Python
и wheel не изменились, скачивания и переустановки не потребовалось.

- [Общий результат](../../.artifacts/s101-published-evidence/summary.json),
  [полный протокол](../../.artifacts/s101-published-evidence/verified.json),
  [независимая сверка](../../.artifacts/s101-published-evidence/independent.json).
- [Сравнение с принятой 101](../../.artifacts/s101-published-evidence/accepted-101-comparison.json),
  [контроллеры без журнала](../../.artifacts/s101-published-evidence/direct-opening-audit.json),
  [повторное использование кеша](../../.artifacts/s101-published-evidence/cache-reuse.json).
- [JUnit CLI](../../.artifacts/s101-published-evidence/reports/cli-suite/cycle/junit.xml),
  [JUnit MCP](../../.artifacts/s101-published-evidence/reports/mcp-suite/cycle/junit.xml),
  [архив проверенного проекта](../../.artifacts/s101-published-evidence/invoice-project.zip).

## Опубликованная поставка

[GitHub Release v0.8.0](https://github.com/AlexanderYekat/1cv7-harness/releases/tag/v0.8.0)
привязан к коммиту `6b6652ccffc3dde4b66f8b75cbba4cdf16858d0f`.
Опубликованы:

- [Wheel](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.8.0/harness77-0.8.0-py3-none-any.whl),
  414429 байт, SHA-256
  `39924cce4e1c6a1b9a7468b2be0176048b979b5661186d8575cc3e680b1adcfa`.
- [sdist](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.8.0/harness77-0.8.0.tar.gz),
  SHA-256 `9bdfe6377b08eafac6cc7755819c70925f56a85b5dfec2bece6b280c10d2a223`.
- [SHA256SUMS.txt](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.8.0/SHA256SUMS.txt).

GitHub API подтверждает digest wheel; draft=false. Аннотированный тег
v0.8.0 указывает на указанный исходный коммит. Сборка получена из git archive
этого коммита, wheel — из sdist. Полная проверка поставки — passed,
615 тестов установленного пакета, skipped=5. В отличие от первоначальной
проверки 101 весь release verifier завершился успешно с разрешёнными
файловыми операциями.

[CI релизного коммита](https://github.com/AlexanderYekat/1cv7-harness/actions/runs/43480744118)
— success: Windows Python 3.11/3.13/3.15, Linux Python 3.13, package Python 3.13
и обязательный ci. [Локальная проверка поставки](../../.artifacts/s101-release-package/summary.json),
[метаданные GitHub](../../.artifacts/s101-release/github-release.json),
[сохранённый CI](../../.artifacts/s101-release/ci-source.json),
[сверка сборки](../../.artifacts/s101-release/build-identity.json).

Хеш опубликованной сборки отличается от локального wheel первоначальной
101: поставка пересобрана из зафиксированного дерева с актуальной документацией.
Все 72 Python-файла и ресурса совпали с принятой 101 после нормализации
переводов строк; новый wheel отдельно проверяется нативной серией.

## Получение в новом проекте

Проект — `C:/MyProjects/h77-101-published/`, результаты —
`C:/MyProjects/h77-101-published-cycle/`. В настройках только версия, URL
опубликованного asset и SHA-256: нет external-python, локального wheel,
bundled_wheel и каталога packages. До первого prepare подходящего кеша не было.
acquisition.json подтвердил source=download, ready=true, enabled=true,
launch_performed=false. Скачанный wheel имеет тот же SHA-256, что GitHub asset
и SHA256SUMS.txt; установка находится в `.harness77/cache/0.8.0-39924cce4e1c6a1b/`.
Маркер `harness77.txt` пустой, локальное правило и launcher находятся в проекте.

[Доказательство получения](../../.artifacts/s101-published-evidence/acquisition-proof.json)
подтверждает побайтное равенство scenario.json, ERT и контроллера с принятой
101. Файлы fixture/reader/steps/expected из дерева Git отличаются только
переводами строк; platform-сценарий с их содержимым побайтно тот же.

## Воспроизведение

В команде подготовки примера используйте `--direct` и вместо `--wheel …`:

```powershell
--url https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.8.0/harness77-0.8.0-py3-none-any.whl --version 0.8.0 --sha256 39924cce4e1c6a1b9a7468b2be0176048b979b5661186d8575cc3e680b1adcfa
```

Остальные явные входы — по [примеру](../../examples/invoice-project/README.md).
Bootstrap проверенной серии — `.artifacts/s101-release-package/venv/Scripts/python.exe`.
После подготовки все операции идут через локальный launcher, а runner/verifier
запускаются Python из acquisition.json. Для повторного получения выбирайте
новый проект/output; исходная тестовая база остаётся прежним внешним входом.

## Заданный объём повторной проверки

Опубликовать исходники принятой 101, GitHub Release v0.8.0, wheel, sdist
и SHA256SUMS.txt. Сборку выполнить из зафиксированного дерева Git;
проверить sdist/wheel, установленный пакет и CI релизного коммита.

Затем создать новый проект вне checkout с явными входами. В настройках
connect хранить только version/URL/SHA-256, без локального wheel, bundle
или прежнего кеша. Первое получение должно действительно выбрать download
опубликованного asset, сверить хеш до установки и подготовить окружение.
Документ 101 открывается и переоткрывается прямо по ссылке fixture,
с точным ожиданием «Печать», без шагов или контроллеров журнала.

Исходный вариант, контролируемая ошибка +1, исправление и повтор идут
с одинаковыми тестами через run, CLI suite и stdio MCP. Дополнительно
повторяются два контроля неверной подписи. Независимо перечитать
raw JSON, MD, UI, run/suite/JUnit, ответы MCP и состояние источника/реестра/
процессов/копии. Сравнить тесты и прикладные результаты с принятой 101.

Публикация меняет источник получения пакета, не бизнес-ожидания.
Нативная квалификация остаётся прежней: Windows / 7.70.027 /
квалифицированные компоненты и DBF-база.

[Принятая 101](101-direct-invoice-caption.md),
[исходная проверка локальной сборки](101-direct-invoice-caption-acceptance.md),
[команды подготовки](../../examples/invoice-project/README.md).
