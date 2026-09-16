import os
import re
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
    database_url: str = field(default_factory=database_url, repr=False)
    cors_origins: list[str] = field(default_factory=lambda: [
        'https://themiddlewatch.com', 'https://www.themiddlewatch.com',
        'http://localhost:5173', 'http://127.0.0.1:5173',
        *filter(None, os.getenv('CORS_ORIGINS', '').split(',')),
    ])
    runs_per_hour: int = 20
    cleanup_interval: float = 300
    netlify_site_name: str = field(default_factory=lambda: os.getenv('NETLIFY_SITE_NAME', '').strip())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv('ANTHROPIC_API_KEY', ''), repr=False)
    anthropic_model: str = field(default_factory=lambda: os.getenv('ANTHROPIC_MODEL', ''))
    resend_api_key: str = field(default_factory=lambda: os.getenv('RESEND_API_KEY', ''), repr=False)
    alert_from: str = field(default_factory=lambda: os.getenv('ALERT_FROM', ''), repr=False)
    alert_to: str = field(default_factory=lambda: os.getenv('ALERT_TO', ''), repr=False)

    @property
    def preview_origin_regex(self):
        if not self.netlify_site_name:
            return None
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', self.netlify_site_name):
            raise ValueError('NETLIFY_SITE_NAME must be a site slug.')
        site = re.escape(self.netlify_site_name)
        return rf'https://(?:deploy-preview-\d+--|[a-z0-9-]+--)?{site}\.netlify\.app'
