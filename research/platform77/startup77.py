"""Bounded native startup evidence; observation timestamps are not target timestamps."""
import time

from shutdown77 import atomic_json


def command_marker(run_id):
    return 'HARNESS77_STARTUP_COMMANDS:' + run_id


def commands_processed(log, run_id):
    lines = log.splitlines()
    count = lines.count(command_marker(run_id))
    if count > 1:
        raise ValueError('duplicate startup command marker')
    return count == 1


class StartupTrace:
    def __init__(self, out, run_id, clock=time.perf_counter):
        self.path = out / 'startup.json'
        self.clock, self.started = clock, clock()
        self.data = {'schema_version': 1, 'run_id': run_id, 'status': 'waiting',
                     'waiting_for': 'registration', 'events': []}
        self.seen = set()
        self.save()

    def save(self):
        atomic_json(self.path, self.data)

    def note(self, stage, *, waiting_for=None, **details):
        if stage in self.seen:
            return
        self.seen.add(stage)
        self.data['events'].append({'stage': stage, 'observed_s': round(self.clock() - self.started, 6), **details})
        if waiting_for is not None:
            self.data['waiting_for'] = waiting_for
        self.save()

    def finish(self, error=None, cancelled=False):
        self.data['status'] = 'cancelled' if cancelled else 'blocked' if error else 'ready'
        if error:
            self.data['error'] = error
        self.save()
