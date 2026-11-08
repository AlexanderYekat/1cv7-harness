"""046: native tab selection, confined to the inspected owned document frame."""
import copy
import struct

GET_COUNT, GET_ITEM, GET_SELECTED = 0x1304, 0x1305, 0x130B


def target(state, caption):
    items = state.get('items', [])
    matches = [i for i, text in enumerate(items) if text.replace('&', '').casefold() == caption.casefold()]
    if len(matches) != 1:
        raise RuntimeError(f'tab {caption!r}: expected one matching native tab, found {len(matches)}')
    if not 0 <= state.get('selected', -1) < len(items):
        raise RuntimeError('native tab selection is invalid')
    return matches[0]


def read(form, inspection):  # native; no code runs on import
    import ctypes as C
    from ctypes import wintypes as W
    from win32_session77 import kernel
    chain = inspection.get('chain', [])
    if len(chain) < 3 or chain[2].get('class') != 'MDIClient':
        raise RuntimeError('tab requires an inspected document MDI frame')
    frame = chain[1]['hwnd']
    candidates = [w for w in form.inventory() if w.get('parent') == frame
                  and w.get('class') == 'SysTabControl32' and w.get('visible') and w.get('enabled')]
    if len(candidates) != 1:
        raise RuntimeError(f'expected one visible native tab control in document frame, found {len(candidates)}')
    window = candidates[0]
    def query(message, index=0, pointer=0):
        ok, value, error = form.send(window['hwnd'], message, index, pointer, ansi=True)
        if not ok:
            raise RuntimeError(f'tab query {message:#x} failed: {error}')
        return value
    count = query(GET_COUNT)
    if not 1 <= count <= 20:
        raise RuntimeError('native tab count must be 1..20')
    # The pinned 7.7 server is x86. TCITEMA uses 32-bit pointers even in a 64-bit watcher.
    kernel.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
    kernel.VirtualAllocEx.restype = C.c_void_p
    kernel.VirtualFreeEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD]
    kernel.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    kernel.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    form.modal.verify()
    handle = kernel.OpenProcess(0x1000 | 0x38, False, form.modal.server['pid'])
    if not handle:
        raise C.WinError(C.get_last_error())
    address, releasable = None, True
    try:
        form.modal.verify()
        address = kernel.VirtualAllocEx(handle, None, 1024, 0x3000, 4)
        if not address or address > 0xFFFFFFFF - 1024:
            raise RuntimeError('cannot allocate x86 tab query buffer')
        def memory(pointer, size):
            data, read_size = C.create_string_buffer(size), C.c_size_t()
            if not kernel.ReadProcessMemory(handle, pointer, data, size, C.byref(read_size)) or read_size.value != size:
                raise C.WinError(C.get_last_error())
            return data.raw
        items = []
        for index in range(count):
            payload = struct.pack('<IIIIiiI', 1, 0, 0, address + 64, 512, 0, 0) + bytes(996)
            written = C.c_size_t()
            if not kernel.WriteProcessMemory(handle, address, payload, len(payload), C.byref(written)) or written.value != len(payload):
                raise C.WinError(C.get_last_error())
            # On timeout the receiver could still reference the buffer. Leave it to server teardown.
            releasable = False
            value = query(GET_ITEM, index, address)
            releasable = True
            if value != 1:
                raise RuntimeError('native tab caption unavailable')
            pointer = struct.unpack('<IIIIiiI', memory(address, 28))[3]
            raw = memory(pointer, 512)
            if b'\0' not in raw:
                raise RuntimeError('native tab caption truncated')
            items.append(raw.split(b'\0', 1)[0].decode('cp1251', errors='strict'))
        selected = query(GET_SELECTED)
        if not 0 <= selected < count:
            raise RuntimeError('native tab selection invalid')
        return dict(window=window, frame=frame, items=items, selected=selected,
                    caption=items[selected], identity_rechecked=True)
    finally:
        if address and releasable:
            kernel.VirtualFreeEx(handle, address, 0, 0x8000)
        kernel.CloseHandle(handle)


def execute(watcher, form, inspection, step, record):
    import scenario77
    before = record['tabs_before'] = read(form, inspection)
    wanted = target(before, step['target'])  # no key is sent for missing or ambiguous captions
    record['tab_keys'] = []
    record['calls'] = []
    current = before
    for unused in range(abs(wanted - before['selected'])):
        name = 'right' if wanted > current['selected'] else 'left'
        focus = form.give_focus(inspection['chain'][0]['hwnd'], current['window']['hwnd'])
        if not focus or focus.get('hwnd') != current['window']['hwnd']:
            raise RuntimeError('cannot focus native document tabs')
        action = form.post_key(current['window']['hwnd'], *scenario77.KEYS[name])
        row = dict(action=action, focus=focus)
        record['tab_keys'].append(row)
        if not action.get('returned'):
            raise RuntimeError('native tab navigation key failed')
        trip = row['round_trip'] = watcher.round_trip(scenario77.trip_number(step['index'], len(record['tab_keys'])))
        record['calls'].append(dict(trip, number=scenario77.trip_number(step['index'], len(record['tab_keys']))))
        if not trip.get('returned') or not trip.get('complete') or trip.get('diagnostics'):
            raise RuntimeError('1C did not complete tab navigation')
        after = row['tabs'] = read(form, inspection)
        if (after['window'] != current['window'] or after['items'] != before['items']
                or after['selected'] != current['selected'] + (1 if name == 'right' else -1)):
            raise RuntimeError('native tab did not move exactly one position')
        current = after
    record['tabs_after'] = current
    record['round_trip'] = watcher.round_trip(step['index'])
    record['calls'].append(dict(record['round_trip'], number=step['index']))
    updated = form.inspect([c['id'] for c in inspection['controls']], frame=before['frame'])
    if not updated.get('found') or updated['chain'][0]['hwnd'] != inspection['chain'][0]['hwnd']:
        raise RuntimeError('tab changed inspected document identity')
    record['tab_form'] = updated
    if 'browser_visible' in step:
        browsers = [c for c in updated['controls'] if c['id'] == scenario77.TABLE_WINDOW_ID]
        if len(browsers) != 1 or browsers[0]['visible'] is not step['browser_visible']:
            raise RuntimeError('tab table visibility differs from declared expectation')
    record['tab_verified'] = current['selected'] == wanted
    # Keep the description immutable: expected visibility describes the entry state only.
    return copy.deepcopy(updated)
