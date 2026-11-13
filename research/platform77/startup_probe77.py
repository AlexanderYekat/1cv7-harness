"""091 diagnostic launcher: controlled loss of CDB module bookkeeping only.

Not part of the exported runtime. No target DLL unload, register edit, retry,
Initialize substitute or change to ownership/cleanup is performed here.
"""
import json
from pathlib import Path
import sys

import harness77

parameters = json.loads(sys.argv[sys.argv.index('--parameters-json') + 1])
runtime = Path(parameters['startup_probe_runtime']).resolve(strict=True)
mode = parameters.get('startup_probe_mode', 'normal')
if mode not in ('normal', 'lost-module', 'unbound', 'hold-factory'):
    raise ValueError('unknown startup probe mode')
sys.path.insert(0, str(runtime / 'native/platform77'))
import proxy_debug77 as observer
import stage4_launcher77 as launcher

prepare = observer.prepare_observer


def controlled(out, run_id, profile=observer.DEFAULT_OBSERVER):
    commands, name = prepare(out, run_id, profile)
    if mode == 'lost-module':
        commands = '.reload /u combase.dll\n' + commands
    elif mode == 'unbound':
        # Deliberately undo the repair in the debugger, before creating bp10.
        commands = commands.replace('bu10 ', '.reload /u combase.dll\nbu10 ', 1)
    elif mode == 'hold-factory':
        script = out / 'identity-register.txt'
        script.write_text(script.read_text(encoding='ascii').replace(
            '.echo HARNESS77_FACTORY_WATCH', '.echo HARNESS77_PROBE_FACTORY_HELD'), encoding='ascii')
    return commands, name


observer.prepare_observer = controlled
raise SystemExit(launcher.main())
