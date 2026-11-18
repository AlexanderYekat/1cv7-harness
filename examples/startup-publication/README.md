# Проверка устойчивой публикации startup.json (109)

`run.py` запускает прежний и исправленный установленные wheel на принятом
Windows/1С 7.70.027/DBF-стенде. Используется неизменённый прикладной сценарий
108 с восемью шагами check_combo/select и проверкой обработчика.

`launch.py` — диагностический launcher: открывает настоящий Windows reader
без FILE_SHARE_DELETE перед публикацией startup trace. Файлы установленного
пакета не изменяются. Наблюдение вызовов и удержание reader выполняются только
в процессе диагностического launcher. Обычные baseline/after-failure/after-cancel
через `run` используют исходный bundled runtime без этой обвязки.

Временные блокировки до debugger_create и после подтверждения ownership
снимаются через 200 мс. В контролях прежнего runtime reader удерживается до
окончания: сама единственная замена иногда ждёт дольше короткого таймера.
Постоянные блокировки должны дать blocked, сохранить прежний JSON и завершить
очистку. Отдельно проверяются короткий open deadline, отмена и восстановление.
Семь основных случаев повторяются через CLI suite и stdio MCP; suite должен
продолжиться после инфраструктурного отказа с проверенной очисткой.

Пример запуска из корня репозитория (пути относятся к локальной квалификации):

```powershell
.artifacts/s109-package-final/venv/Scripts/python.exe -B examples/startup-publication/run.py `
  --project .artifacts/s108-native-project/project.toml `
  --stand .artifacts/s108-native-project/stand.toml `
  --old-python .artifacts/s108-package/venv/Scripts/python.exe `
  --output .artifacts/s109-native-final
python -B examples/startup-publication/verify.py `
  --native .artifacts/s109-native-final --package .artifacts/s109-package-final
```

Выходной каталог должен быть новым; `--resume` допускается только для того же
пакета и неизменного состояния стенда. До и после каждого запуска сверяются
исходная база, MD/DD/DLL, реестр, чужие процессы, отсутствие копии и lock.
`verify.py` независимо перечитывает отчёты, исходы, telemetry и хэши всех
установленных файлов wheel и 33 native-исходников. Отчёты и SHA-256 сохраняются
в `.artifacts`; launcher не исправляет права, не снимает readonly и не подменяет
реальные ошибки файловой системы искусственными исключениями.
