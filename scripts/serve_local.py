"""Migrate the local database and serve the API for browser checks."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True)
if __name__ == '__main__':
    import uvicorn
    uvicorn.run('api.main:app', host='127.0.0.1', port=8000)
