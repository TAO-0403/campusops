import os

import pytest

from app.config import get_database_settings
from app.db import connect
from app.migrate import apply_migrations
from app.seed_demo import seed_demo_users


def _require_test_database(database_name: str) -> None:
    with connect("postgres") as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s AND datallowconn = TRUE",
            (database_name,),
        ).fetchone()
    if exists is None:
        raise RuntimeError("Create an empty 'campusops_test' database owned by the configured application role before running tests.")


@pytest.fixture(autouse=True)
def isolated_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    development_database = get_database_settings()["dbname"]
    test_database = os.getenv("CAMPUSOPS_TEST_DATABASE", "campusops_test")

    if not test_database.endswith("_test") or test_database == development_database:
        raise RuntimeError("Tests require a separate database whose name ends with '_test'.")

    _require_test_database(test_database)
    monkeypatch.setenv("PGDATABASE", test_database)
    apply_migrations(test_database)

    with connect(test_database) as connection:
        connection.execute(
            "TRUNCATE TABLE auth_sessions, request_events, purchase_requests, users RESTART IDENTITY CASCADE"
        )
    seed_demo_users(test_database)
