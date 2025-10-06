import nbformat as nbf
from pathlib import Path

for path in [Path('stealth_monitor/notebooks/stealth_dashboard.ipynb'), Path('Untitled.ipynb')]:
    nb = nbf.read(path, as_version=4)
    print('---', path)
    for cell in nb.cells:
        if cell['cell_type'] == 'code':
            print(cell['source'])
            print('---')
            break
