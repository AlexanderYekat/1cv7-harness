from pathlib import Path
import sys
import zlib
import struct
import re

sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / '1cv77-devtools'))
from ert_module import CompoundFile

cf = CompoundFile((root / '.local' / 'configurations' / 'reference' / '1Cv7.MD').read_bytes())
entries = cf.directory_entries
paths = {}

def walk(index, parent):
    if index == 0xffffffff:
        return
    entry = entries[index]
    left, right, child = struct.unpack_from('<III', entry.raw, 68)
    walk(left, parent)
    path = parent + '/' + entry.name if parent else entry.name
    paths[index] = path
    if entry.object_type in (1, 5):
        walk(child, path)
    walk(right, parent)

walk(struct.unpack_from('<I', entries[0].raw, 76)[0], '')
out = root / '.local' / 'research' / '76av' / 'modules'
out.mkdir(exist_ok=True)
for entry in entries:
    if entry.object_type != 2:
        continue
    path = paths.get(entry.entry_id, entry.name)
    if entry.name == 'Main MetaData Stream':
        text = cf.read_stream(entry).decode('cp1251', errors='replace')
        (out.parent / 'metadata.txt').write_text(text.replace('\r\n', '\n'), encoding='utf-8', newline='\n')
    if 'MD Programm text' not in entry.name:
        continue
    raw = cf.read_stream(entry)
    try:
        raw = zlib.decompress(raw, -15)
    except zlib.error:
        pass
    text = raw.decode('cp1251', errors='replace')
    if not re.search(r'76\.?[АA][ВB]|НДС.*[Пп]редоплат|[Пп]редоплат.*НДС', text):
        continue
    name = path.replace('/', '__') + '.txt'
    (out / name).write_text(text.replace('\r\n', '\n'), encoding='utf-8', newline='\n')
    lines = text.splitlines()
    hits = [(i + 1, line.strip()) for i, line in enumerate(lines)
            if re.search(r'76\.?[АA][ВB]|НДС.*[Пп]редоплат|[Пп]редоплат.*НДС', line)]
    print(path, 'LINES', len(lines), 'HITS', len(hits))
    for i, line in hits[:18]:
        print(f'{i}: {line[:250]}')
