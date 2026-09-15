from extrio.config import get_settings


def test_default_test_instance_never_uses_checkout_data():
    settings = get_settings()
    for path in (
        settings.database_path,
        settings.artifact_path,
        settings.signing_private_key_path,
        settings.credential_encryption_key_path,
    ):
        assert any(part.startswith("extrio-pytest-") for part in path.parts)


def test_postgresql_probe_requires_explicit_configuration(monkeypatch):
    import test_store_pg

    monkeypatch.setattr(test_store_pg, "TEST_DATABASE_URL", None)

    def unexpected_connection(*args, **kwargs):
        raise AssertionError("Unconfigured tests must not connect to a local PostgreSQL server")

    monkeypatch.setattr(test_store_pg.psycopg, "connect", unexpected_connection)
    assert test_store_pg._postgres_available() is False
