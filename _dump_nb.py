import json
from pathlib import Path

for path in [Path('stealth_monitor/notebooks/stealth_dashboard.ipynb'), Path('Untitled.ipynb')]:
    nb = json.loads(path.read_text(encoding='utf-8'))
    print('====', path)
    for i, cell in enumerate(nb['cells']):
        print(f'Cell {i} type={cell["cell_type"]}')
        if cell['cell_type'] == 'code':
            print(cell['source'])
            print('---')
    print()
