import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
VERSION = '2.0.0'
FEED_NOTICE = 'Simulated feed — journeys are generated, no carrier is contacted.'


def database_url():
    value = os.getenv('DATABASE_URL') or f'sqlite:///{(ROOT / "api" / "middlewatch.db").as_posix()}'
    for prefix in ('postgres://', 'postgresql://'):
        if value.startswith(prefix):
            return value.replace(prefix, 'postgresql+psycopg://', 1)
    return value


@dataclass
class Settings:
    database_url: str = field(default_factory=database_url)
    cors_origins: list[str] = field(default_factory=lambda: [
        'https://themiddlewatch.com', 'https://www.themiddlewatch.com',
        'http://localhost:5173', 'http://127.0.0.1:5173',
        *filter(None, os.getenv('CORS_ORIGINS', '').split(',')),
    ])
    runs_per_hour: int = 20
