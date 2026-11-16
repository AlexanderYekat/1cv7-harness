# Создание COMBOBOX в существующей ERT

Пример 107 добавляет список в описание формы FIO.ERT закреплённого
Windows/1С 7.70.027/DBF-стенда. Нужны установленный harness77 с поддержкой
создания COMBOBOX и профиль forms-стенда с актуальными helper/identity,
копированием базы и явным `copy_path`.

```powershell
python examples/combo-creation/prepare.py --template <путь-к-FIO.ERT> --stand <stand.toml> --output .local/combo107
python -m harness77 run --project .local/combo107/project.toml --stand .local/combo107/stand.toml
python examples/combo-creation/run.py --project .local/combo107/project.toml --stand .local/combo107/stand.toml --output .artifacts/combo107-cycle
python examples/combo-creation/verify.py --cycle .artifacts/combo107-cycle --template <путь-к-FIO.ERT>
```

Подготовка создаёт редактируемые `form.json`, `module.1s`, `steps.json` и
`project.toml`. База копируется перед каждым запуском. Модуль заполняет
пункты «Первый», «Второй», пустую строку и ещё один «Второй».
`inspect_combo` сохраняет их без вызова обработчика; повтор выбора первого
пункта — no-op; выбор пустого пункта вызывает обработчик ровно один раз.
Дубликат «Второй» не используется для `select`, который требует единственный текст.

Полный цикл создаёт четыре профиля с одинаковыми формой и шагами. Только
в regression счётчик обработчика увеличивается на 2 вместо 1. Ожидаются
passed/failed/passed/passed в каждом из run, CLI suite и stdio MCP.
Проверяются snapshots и SHA-256, геометрия, JSON/JUnit, ping MCP,
сохранность базы/реестра/чужих процессов и очистка копии.

Пути и состав старой FIO.ERT привязаны к квалифицированному шаблону;
другой шаблон требует подобрать свободную область и доступные обработчики.
