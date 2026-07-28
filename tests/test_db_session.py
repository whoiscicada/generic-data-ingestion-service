import pytest

from app.db import session


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("postgres://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("postgresql://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        ("postgresql+asyncpg://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
    ],
)
def test_get_database_url_normalizes_to_asyncpg_dialect(monkeypatch, raw, expected):
    monkeypatch.setenv("DATABASE_URL", raw)
    assert session.get_database_url() == expected


def test_get_database_url_raises_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        session.get_database_url()
