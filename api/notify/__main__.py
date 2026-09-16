"""Explicit operator command: python -m api.notify WATCHLIST_UUID."""
import argparse
from uuid import UUID
from api.config import Settings
from api.db import connect
from api.db.models import Watchlist, now
from api.notify import send_alert
from api.services.watchlists import watchlist_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('watchlist_id', type=UUID)
    args = parser.parse_args()
    settings = Settings()
    engine, sessions = connect(settings.database_url)
    try:
        with sessions() as session:
            watchlist = session.get(Watchlist, str(args.watchlist_id))
            if watchlist is None or watchlist.expires_at <= now():
                raise SystemExit('Watchlist not found or expired.')
            result = send_alert(watchlist_payload(watchlist), settings)
            print(result['message'])
            return 1 if result['status'] == 'unavailable' else 0
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
