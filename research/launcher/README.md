# Пробы launcher (задача 015)

`launcher_probes77.py` — нативные пробы [задачи 015](../../docs/tasks/015-launcher-robustness.md):
каждый случай пишет `<output>/<случай>.json` с командой, кодом выхода, главным из `run.json`
и снимками до и после — ключи временной регистрации COM (запись `Harness77Owner`
раскодирована), процессы 1С/cdb/cscript, след на базе.

```powershell
python -B research/launcher/launcher_probes77.py gate-take
python -B research/launcher/launcher_probes77.py L0 --output .artifacts/launcher/<новый>/L0
python -B research/launcher/launcher_probes77.py L4 --output .artifacts/launcher/<новый>/L4
python -B research/launcher/launcher_probes77.py L5 --output .artifacts/launcher/<новый>/L5
python -B research/launcher/launcher_probes77.py L1 --output .artifacts/launcher/<новый>/L1
python -B research/launcher/launcher_probes77.py L2 --output .artifacts/launcher/<новый>/L2
python -B research/launcher/launcher_probes77.py L3 --output .artifacts/launcher/<новый>/L3
python -B research/launcher/launcher_probes77.py L6 --output .artifacts/launcher/<новый>/L6 `
  [--run-args "--open-timeout-s 600 --shutdown-timeout-s 120 --total-timeout-s 1000"]
python -B research/launcher/launcher_probes77.py P2 --output .artifacts/launcher/<новый>/P2
python -B research/launcher/launcher_probes77.py gate-release
python -B research/launcher/launcher_probes77.py R1 --output .artifacts/launcher/<новый>/R1
```

Профили — `.local/stage14-native` (`--profiles`). L1 снимает дерево `harness77 run`
(`taskkill /T /F`) и оставляет на базе след прерванного сеанса — следующей должна идти L2
(профиль с запасом на переиндексацию). L4 создаёт ключи прежнего вида и удаляет их, только
если launcher их не тронул; при любых ключах до пробы она не запускается. `gate-take` держит
gate исследования (`.artifacts/platform77/active-session.json`), чтобы задания `kudir` сразу
отказывали; `gate-release` снимает только свою запись. R1 (`run_ert77.py`) берёт gate сам.
P2 ([задача 017](../../docs/tasks/017-poll-round.md)) — обычный запуск, пока 4 процесса без
перерыва пишут файлы по 64 МБ с `fsync` в `<output>/io-load` (после пробы каталог удаляется).
Перед серией убедиться, что на стенде нет чужого сеанса с ключами `Harness77Diagnostic.*`.
