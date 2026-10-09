"""Run legacy tests in a disposable copy so their cleanup cannot delete user uploads."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parent.parent
target = (root / '.cache' / 'test-runs' / uuid.uuid4().hex).resolve()
assert target.is_relative_to((root / '.cache' / 'test-runs').resolve())
target.mkdir(parents=True)
for name in ('backend','config','data','mocks','templates','assets','prompts','scripts','tests','frontend'):
    shutil.copytree(root / name, target / name, ignore=shutil.ignore_patterns('node_modules','__pycache__','.vite'))
shutil.copy2(root / 'pyproject.toml', target / 'pyproject.toml')
env = {**os.environ, 'SARVAM_MOCK':'true', 'DEMO_CACHE':'0', 'SARVAM_API_KEY':'', 'PYTHONIOENCODING':'utf-8'}
failed = []
for suite in sorted((target / 'tests').glob('test_*.py')):
    print(f'\nTesting {suite.name}', flush=True)
    if subprocess.run([sys.executable,'-m','pytest',str(suite),'-q','--tb=short'],cwd=target,env=env).returncode:
        failed.append(suite.name)
print('Failed suites:', failed, flush=True)
print('Isolated artifacts:', target, flush=True)
raise SystemExit(bool(failed))
