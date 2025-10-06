import nbformat as nbf
from pathlib import Path

path = Path('stealth_monitor/notebooks/display_steps.ipynb')
nb = nbf.read(path, as_version=4)
cell = nb.cells[16]
print(''.join(cell['source']))
