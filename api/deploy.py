"""Migrate before listening, without exposing connection details on failure."""
import os
import sys
from alembic import command
from alembic.config import Config
from api.config import ROOT, Settings


def prepare():
    settings = Settings()
    if os.getenv('RENDER') == 'true' and not settings.database_url.startswith('postgresql+psycopg://'):
        raise ValueError('Hosted API requires a Postgres database configured in the dashboard.')
    command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')


def main():
    try:
        prepare()
        port = int(os.getenv('PORT', '8000'))
        if not 1 <= port <= 65535:
            raise ValueError('Invalid port.')
    except Exception:
        print('Startup blocked: check database configuration, connectivity, migrations and PORT in the hosting dashboard.', file=sys.stderr)
        return 1
    import uvicorn
    uvicorn.run('api.main:app', host='0.0.0.0', port=port, workers=1,
        proxy_headers=False, access_log=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
