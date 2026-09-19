from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect
from api.config import ROOT, Settings
from api.db import connect
from api.deploy import prepare
from api.guardrails import client_address


def test_startup_migration_is_repeatable(tmp_path, monkeypatch):
    url = 'sqlite:///' + (tmp_path / 'deploy.db').as_posix()
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.delenv('RENDER', raising=False)
    prepare()
    prepare()
    command.check(Config(str(ROOT / 'alembic.ini')))
    engine, _ = connect(url)
    try:
        assert {'watchlist', 'container', 'event', 'exception'} <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_render_requires_persistent_database(monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    with pytest.raises(ValueError, match='Postgres'):
        prepare()


def test_failed_migration_never_starts_server_or_logs_details(monkeypatch, capsys):
    from api import deploy
    def broken():
        raise RuntimeError('private-connection-detail')
    monkeypatch.setattr(deploy, 'prepare', broken)
    assert deploy.main() == 1
    output = capsys.readouterr()
    assert 'Startup blocked' in output.err
    assert 'private-connection-detail' not in output.err


def test_proxy_header_requires_render_and_private_peer():
    scope = {'client': ('10.1.2.3', 123), 'headers': [(b'true-client-ip', b'192.0.2.10'),
        (b'x-forwarded-for', b'198.51.100.7')]}
    assert client_address(scope) == '10.1.2.3'
    assert client_address(scope, True) == '192.0.2.10'
    scope['client'] = ('203.0.113.5', 123)
    assert client_address(scope, True) == '203.0.113.5'
    scope['client'] = ('10.1.2.3', 123)
    scope['headers'] = [(b'true-client-ip', b'invalid')]
    assert client_address(scope, True) == '10.1.2.3'
    scope['headers'] = [(b'true-client-ip', b'192.0.2.10')] * 2
    assert client_address(scope, True) == '10.1.2.3'


def test_settings_representation_omits_connection_and_service_values():
    settings = Settings(database_url='private-database', anthropic_api_key='private-service', resend_api_key='private-mail')
    assert 'private-' not in repr(settings)
