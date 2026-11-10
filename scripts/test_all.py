"""Run each module's tests in an isolated Python process."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    failed = []
    for module in ('beads', 'minecraft', 'printing', 'quantum'):
        print(f'\n[{module}]', flush=True)
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', f'{module}/tests', '-v'], cwd=ROOT)
        if result.returncode:
            failed.append(module)
    if failed:
        print('Failed modules: ' + ', '.join(failed), file=sys.stderr)
        sys.exit(1)
    print('\nAll module tests passed.')
