# Проверка 099: локальное подключение

13 ноября 2026 года. Реализация и локальные/нативные проверки завершены.
Задача принята владельцем 13 ноября 2026 года.
По разрешению владельца отправлен master с четырьмя предыдущими локальными
коммитами и реализацией 099; опубликован GitHub Release v0.7.0.
Настоящее скачивание из него и запуск через локальную команду подтверждены.

## Поставка

Wheel 0.7.0 собран из sdist, офлайн установлен в новый venv без pip.
[Отчёт](../../.artifacts/s99-distribution/summary.json): **passed**, 615 тестов,
610 успешных и пять пропусков (Windows symlink/проверка другой OS).
Новые проверки покрывают локальные файлы и сохранение пользовательских данных,
атомарную запись AGENTS, откат, идемпотентность, неоднозначные профили,
приоритет источников, ошибки версии/хеша, повреждение кеша/квитанции,
конкурирующую подготовку, отключение до чтения config и живой MCP.

Wheel SHA-256:
`7f0f81e8ead500ba97920bbb37c316d4680ecc6e0b064bd97fa4ad405ab57d6f`.

## Получение и автономный запуск

[Серия](../../.artifacts/s99-local/verified.json): **passed**.
Независимо проверены внешний установленный пакет, внешний wheel, bundled wheel
и настоящий HTTP download через pip. В каждом — doctor, run, CLI suite,
stdio MCP suite, отключение до первого получения и после работы, в том числе
tools/call уже открытого сервера с сохранением ping. Проверка проходит из другого
CWD, без PYTHONPATH/PYTHONHOME, через копию самодостаточного launcher, в путях
с кириллицей и пробелами. Исходные профили и прикладные файлы сохранены.

Сервер закрыт после загрузки: повтор использует проверенное окружение, без сети
и переустановки (хеши и mtime сохранены). Перенесённый проект без кеша/venv
заново подготовлен и выполнил run офлайн. Два реальных процесса prepare не
выдают частично готовое окружение. Неверный SHA-256 отклонён настоящим pip
до установки; повреждённый установленный пакет и недоступная сеть без кеша
дают blocked/2, без молчаливой замены. Ошибка подготовки не оставляет ready/lock.

HTTP в этой серии — loopback-сервер с настоящим wheel, не опубликованный релиз.

Отдельно повторены все проверки вне checkout: начальный установленный пакет,
новые прикладные каталоги, bootstrap и CWD находятся вне репозитория.
[Отчёт](../../.artifacts/s99-evidence/outside-final.json), оригиналы —
`C:/MyProjects/h77-099-final/`. После отрицательных контролей конфигурация
и пакет восстановлены; готовность проверенного кеша повторно подтверждена офлайн.

## Нативный цикл из финального wheel

[Полная серия](../../.artifacts/s99-evidence/native-verified.json): **passed**.
Комплект `C:/MyProjects/h77-099-kit/`, venv без pip с единственным harness77,
рабочий каталог и все результаты `C:/MyProjects/h77-099-native/` находятся
вне checkout. PYTHONPATH/PYTHONHOME отсутствуют; дочерние launcher, CLI, MCP
и нативный исполнитель используют установленный пакет. Все 39 файлов ядра
совпадают с финальным wheel и checkout, 33 нативных файла — с принятой 098.

doctor и три run, оба CLI suite и три запроса MCP suite выполнены через
`.harness77/launch.py`, с сохранённой привязкой существующей базы:

- Прямые baseline/regression/fixed: **passed/failed/passed**, коды 0/1/0.
- CLI и MCP regression: **passed/failed/passed/passed**, итог failed/1,
  counts 3/1/0/0, по одному JUnit failure, у MCP isError=false.
- CLI и MCP invalid-results: **blocked/blocked/passed**, итог blocked/2,
  counts 1/0/2/0, по два JUnit error; у MCP isError=true.
- Следующий suite того же MCP: passed/0, isError=false. Ping проходит
  во время и после запросов; прогресс и progressToken проверены.
- После удаления harness77.txt новый tools/call того же MCP возвращает
  disabled/isError=true без дочерней операции; ping остаётся доступен.

Регрессия сохраняет те же два расхождения `/entries/0/amount` и
`/entries/1/amount`: 30→10 и 40→20, с прежними русскими подписями. JSON,
suite.problems и JUnit согласованы; нормализованные CLI/MCP результаты равны.
Все 18 нативных запусков подтвердили один Initialize, владение процессами,
штатную очистку без forced_cleanup, удаление копии и освобождение замка.
Сверены 3598 потоков каждой из семи плановых MD; только регрессия меняет
единственный поток модуля проведения. Исходная база/MD/DD/DLL, реестр,
чужие процессы, guard, kit, runtime и профили сохранены.

[Независимое перечитывание](../../.artifacts/s99-evidence/native-reread.json)
подтвердило семь проектов и все 18 запусков.
[Контроли проектов](../../.artifacts/s99-project-controls/controls.json)
отклонили 15 подмен, повторно сверили MD, окружение и состояние стенда.
[Контроли suite](../../.artifacts/s99-suite-controls-final/controls.json)
отклонили 33 подмены raw JSON/UI/run/suite/JUnit, включая согласованное
пересчитывание хешей. Оригиналы повторно перечитаны и сохранены.
Для запуска verifier из самостоятельного комплекта исправлен поиск
соседнего suite_verify без PYTHONPATH.

До финального wheel также выполнена полная предварительная серия из
18 нативных запусков; она хранится отдельно в `.artifacts/s99-native/`
и не подменяет приведённую выше проверку окончательного дистрибутива.
Автоматических повторов нативных случаев не добавлялось.

## Артефакты и охват

[Общая сверка](../../.artifacts/s99-evidence/summary.json),
[переносимый демонстрационный проект](../../.artifacts/s99-evidence/portable-project.zip)
содержит правило, маркер, launcher/config, профили, входы и bundled wheel,
без venv/кеша/результатов. Архив перечитан, все хеши проверены; демонстрация
использует simulation. Самостоятельный нативный комплект и команды —
в [примере](../../examples/local-activation/README.md).

Квалификация нативной части ограничена Windows / 7.70.027 и документом
«Готовая продукция» из 098. Новые стенды, документы, глобальная регистрация
MCP и skills не добавлялись.

## Опубликованный источник и проверка GitHub

[GitHub Release v0.7.0](https://github.com/AlexanderYekat/1cv7-harness/releases/tag/v0.7.0)
опубликован из коммита `98c93051bf6dc1be2e2dc4262af15ced301a700e`.
Публичный источник —
[harness77-0.7.0-py3-none-any.whl](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.7.0/harness77-0.7.0-py3-none-any.whl),
рядом опубликован
[SHA256SUMS.txt](https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.7.0/SHA256SUMS.txt).
GitHub подтверждает digest `sha256:7f0f81e8ead500ba97920bbb37c316d4680ecc6e0b064bd97fa4ad405ab57d6f`,
размер wheel — 413028 байт; это тот же дистрибутив, на котором проведена нативная серия.

В новом каталоге `C:/MyProjects/h77-099-github/`, вне checkout, повторена полная
серия получения с `--url` опубликованного asset.
[Отчёт](../../.artifacts/s99-evidence/github-download.json): **passed**.
Первый prepare выбирает download без локального wheel или кеша, pip получает
реальный GitHub asset, проверяет SHA-256 и устанавливает его изолированно.
Через эту локальную команду прошли doctor, run, CLI suite и stdio MCP suite.
Повтор выбирает cache, сохраняет Python, хеши и mtime; удаление маркера блокирует
новую операцию живого MCP. Реальное скачивание с неверным хешем отвергнуто
до установки. Недоступная сеть без подходящего кеша проверена отдельным
loopback-адресом; после отрицательных контролей исходные настройки восстановлены.

```powershell
python -B scripts/verify_local_activation77.py --wheel .artifacts/s99-distribution/dist/harness77-0.7.0-py3-none-any.whl --installed-python C:/MyProjects/h77-099-kit/venv/Scripts/python.exe --template C:/MyProjects/h77-099-kit/inputs/template.ert --output C:/MyProjects/h77-099-github --url https://github.com/AlexanderYekat/1cv7-harness/releases/download/v0.7.0/harness77-0.7.0-py3-none-any.whl
```

Выбирайте новый output для повтора. Полная проверка исходного коммита
[CI](https://github.com/AlexanderYekat/1cv7-harness/actions/runs/43446005680) —
**success**: Windows Python 3.11/3.13/3.15, Linux Python 3.13,
сборка sdist/wheel и установленный пакет; общий обязательный ci также успешен.
[Сохранённые метаданные релиза](../../.artifacts/s99-evidence/github-release.json)
и [CI](../../.artifacts/s99-evidence/github-ci.json).
