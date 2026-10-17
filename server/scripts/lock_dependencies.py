"""Regenerate hash-locked runtime and test dependencies (Python 3.12/3.13).

Install pip-tools==7.6.2 first. Review both diffs and run pip-audit afterwards.
"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ('requirements', 'requirements-dev'):
    subprocess.run([
        sys.executable, '-m', 'piptools', 'compile', '--generate-hashes',
        '--resolver=backtracking', '--strip-extras', '--no-emit-index-url',
        '--no-emit-trusted-host', '--upgrade', f'--output-file={name}.txt', f'{name}.in',
    ], cwd=root, check=True)
