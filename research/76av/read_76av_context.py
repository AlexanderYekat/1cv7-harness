from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[2] / '.local' / 'research' / '76av'
metadata = (root / 'metadata.txt').read_text(encoding='utf-8')
for line in metadata.splitlines():
    if any('"' + x + '",' in line for x in ('294', '321', '11012')):
        print(line[:600])
for key, start, end in [('Transact_Number321', 320, 517), ('Transact_Number294', 830, 951)]:
    p = next((root / 'modules').glob('*' + key + '__*.txt'))
    print('\nFILE', p.name)
    for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
        if start <= i <= end:
            print(f'{i}: {line}')
