# Изменение модулей 1Cv7.MD на копии базы (задача 021)

Нативные пробы [задачи 021](../../docs/tasks/021-md-modules.md): модули конфигурации базы
стенда меняются через `[configuration]` профиля проекта, `harness77 run` собирает `1Cv7.MD`,
открывает в 1С копию базы и проверяет, что 1С исполнила именно собранную конфигурацию.
Итоги и выводы — в [приёмке](../../docs/tasks/021-md-modules-acceptance.md).

`probe_md77.py` — каждый случай один `harness77 run`: в каталог `configuration` случая пишутся
только изменённые файлы раскладки `md-extract` (текст модуля базы стенда с правкой случая),
модуль обработки — контрольная функция `Harness77Контроль` по образцу `rules77/probe_rules77.py`.
Ожидания записаны в задании до прогона; `--final` — третья серия с ожиданиями по первым двум.
После серии проверяется, что перечень файлов базы стенда и список баз 1С не изменились.

Стенду нужны `[stand.base] copy_path` — путь копии, зарегистрированный в списке баз 1С
(`HKCU\Software\1C\1Cv7\7.7\Titles`; через OLE 1С 7.7 открывает только зарегистрированную
базу), — и `copy_exclude`. Локальный профиль задачи — `.local/stage21-native/stand.toml`.

```powershell
python research/md/probe_md77.py --stand .local/stage21-native/stand.toml `
    --template .local/bases/base-for-test/ExtForms/rp14q1.GRP/FIO.ERT `
    --work .local/stage21-native/s1 --evidence .artifacts/stage21-md-probes-YYYYMMDD-1.json
python research/md/probe_md77.py --final ... --work .local/stage21-native/s3 `
    --evidence .artifacts/stage21-md-probes-YYYYMMDD-3.json
```

Свод серий и круговая проверка `md-extract` → `md-build` на конфигурациях —
`scripts/verify_md77.py` (команда в шапке скрипта).
