"""Delete expired watchlists and their dependent rows without reading payloads."""
import asyncio
import logging
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from api.db.models import Watchlist, now


def cleanup(sessions):
    with sessions() as session:
        result = session.execute(delete(Watchlist).where(Watchlist.expires_at <= now()))
        session.commit()
        return result.rowcount


async def scheduled_cleanup(sessions, interval=300):
    while True:
        try:
            await asyncio.to_thread(cleanup, sessions)
        except SQLAlchemyError:
            # Never log connection strings, parameters, or exception text.
            logging.getLogger(__name__).warning('Retention cleanup unavailable; retry scheduled.')
        await asyncio.sleep(interval)


if __name__ == '__main__':
    from api.config import Settings
    from api.db import connect
    engine, sessions = connect(Settings().database_url)
    try:
        print(f'Deleted {cleanup(sessions)} expired watchlists.')
    finally:
        engine.dispose()
