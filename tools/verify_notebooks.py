# -*- coding: utf-8 -*-
import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_NOTEBOOKS = [
    Path('stealth_monitor/notebooks/testview.ipynb'),
]


def execute_notebook(nb_path: Path, output_dir: Path, timeout: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = nb_path.with_suffix('.executed.ipynb').name
    cmd = [
        sys.executable,
        '-m',
        'jupyter',
        'nbconvert',
        '--execute',
        '--to',
        'notebook',
        '--output',
        output_name,
        '--output-dir',
        str(output_dir),
        f'--ExecutePreprocessor.timeout={timeout}',
        str(nb_path),
    ]
    print(f'Executing {nb_path} ...')
    subprocess.run(cmd, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Execute notebooks via nbconvert for verification.')
    parser.add_argument(
        '--notebook',
        action='append',
        dest='notebooks',
        help='Notebook path to execute; can be provided multiple times.',
    )
    parser.add_argument(
        '--output-dir',
        default='outputs/nbconvert',
        help='Directory to store executed notebooks.',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=600,
        help='Execution timeout (seconds) per notebook.',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    notebook_paths = args.notebooks or [str(nb) for nb in DEFAULT_NOTEBOOKS]
    notebooks = [Path(nb) for nb in notebook_paths]
    output_dir = Path(args.output_dir)

    for nb_path in notebooks:
        if not nb_path.exists():
            raise FileNotFoundError(f'Notebook not found: {nb_path}')
        execute_notebook(nb_path, output_dir, args.timeout)


if __name__ == '__main__':
    main()
