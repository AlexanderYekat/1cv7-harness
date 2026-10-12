"""Observe a nonce lookup in the owned server's IDispatch, without Invoke.

Only debugger pseudo-registers are assigned. There are no instruction skips or
target register assignments. Breakpoints discover vtables at runtime through COM's
documented IClassFactory/IUnknown/IDispatch ABI (the fixed target is x86).
"""
import re
import uuid

OBSERVER_PROFILES = ("continuous-v1", "challenge-only-v2")
DEFAULT_OBSERVER = "challenge-only-v2"


def challenge_name(run_id):
    return "H77_" + uuid.UUID(run_id).hex


def prepare_observer(out, run_id, profile=DEFAULT_OBSERVER):
    if profile not in OBSERVER_PROFILES:
        raise ValueError("unknown identity observer profile")
    name = challenge_name(run_id)
    def callback(file):
        return '"$><' + (out / file).as_posix() + '"'

    files = {
        "identity-register.txt":
            '.if (dwo(poi(@esp+4)) == 0x63112d81) { '
            'r @$t0=poi(@esp+8); bp11 /1 poi(poi(@$t0)+0xc) ' + callback("identity-factory.txt") +
            '; .echo HARNESS77_FACTORY_WATCH }; gc\n',
        "identity-factory.txt":
            'r @$t1=poi(@esp+0x10); r @$t3=dwo(poi(@esp+0xc)); '
            'bp12 /1 poi(@esp) ' + callback("identity-created.txt") + '; gc\n',
        "identity-created.txt":
            '.if (@eax == 0) { r @$t2=poi(@$t1); '
            '.if (@$t3 == 0x20400) { bp15 poi(poi(@$t2)+0x14) ' + callback("identity-names.txt") +
            ' } .else { bp13 poi(poi(@$t2)) ' + callback("identity-query.txt") +
            ' }; .echo HARNESS77_OBJECT_CREATED }; gc\n',
        "identity-query.txt":
            '.if (dwo(poi(@esp+8)) == 0x20400) { r @$t4=poi(@esp+0xc); '
            'bp14 /1 poi(@esp) ' + callback("identity-dispatch.txt") + ' }; gc\n',
        "identity-dispatch.txt":
            '.if (@eax == 0) { r @$t5=poi(@$t4); bp15 poi(poi(@$t5)+0x14) ' + callback("identity-names.txt") +
            '; .echo HARNESS77_DISPATCH_WATCH }; gc\n',
        "identity-names.txt":
            '.printf "HARNESS77_LOOKUP:%mu:%x:%x\\n", poi(poi(@esp+0xc)), @$tpid, @$tid; gc\n',
    }
    if profile == "challenge-only-v2":
        # The first lookup must be the nonce. Any earlier lookup fails closed:
        # the controller never permits Initialize without the exact challenge.
        # These are the only breakpoints in this private CDB. Exception filters
        # (especially first-chance AV) are independent and remain installed.
        files["identity-names.txt"] = (
            '.printf "HARNESS77_LOOKUP:%mu:%x:%x\\n", poi(poi(@esp+0xc)), @$tpid, @$tid; '
            'bc *; .echo HARNESS77_OBSERVER_EMPTY_BEGIN:' + run_id + '; bl; '
            '.echo HARNESS77_OBSERVER_EMPTY_END:' + run_id + '; gc\n')
    for file, contents in files.items():
        (out / file).write_text(contents, encoding="ascii")
    return 'bu10 combase!CoRegisterClassObject ' + callback("identity-register.txt") + '\n', name


def observed_identity(log, run_id, server):
    name = challenge_name(run_id)
    matches = re.findall(r"^HARNESS77_LOOKUP:" + re.escape(name) + r":([0-9a-fA-F]+):([0-9a-fA-F]+)$", log, re.MULTILINE)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("duplicate identity challenge")
    pid, tid = (int(value, 16) for value in matches[0])
    if pid != server["pid"]:
        raise ValueError("challenge observed in unexpected process")
    return {"run_id": run_id, "pid": pid, "tid": tid, "method": "debugger-observed-GetIDsOfNames", "challenge": name}


def observer_retired(log, run_id, server):
    """Require the nonce, an empty breakpoint list, and no further lookups."""
    if observed_identity(log, run_id, server) is None:
        return False
    begin = "HARNESS77_OBSERVER_EMPTY_BEGIN:" + run_id
    end = "HARNESS77_OBSERVER_EMPTY_END:" + run_id
    lines = log.splitlines()
    if begin not in lines or end not in lines:
        return False
    if lines.count(begin) != 1 or lines.count(end) != 1:
        raise ValueError("duplicate observer retirement")
    first, last = lines.index(begin), lines.index(end)
    lookups = [i for i, line in enumerate(lines) if line.startswith("HARNESS77_LOOKUP:")]
    if last != first + 1 or len(lookups) != 1 or lookups[0] >= first:
        raise ValueError("observer remained active or retirement evidence is invalid")
    return True
