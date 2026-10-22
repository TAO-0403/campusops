from pathlib import Path

from app.db import connect

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[1] / "migrations"


def apply_migrations(database: str | None = None) -> list[str]:
    applied_now: list[str] = []
    with connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        applied = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

        for migration in sorted(MIGRATIONS_DIRECTORY.glob("[0-9]*.sql")):
            if migration.name in applied:
                continue
            with connection.transaction():
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (migration.name,),
                )
            applied_now.append(migration.name)

    return applied_now


if __name__ == "__main__":
    migrations = apply_migrations()
    if migrations:
        for migration_name in migrations:
            print(f"Applied migration: {migration_name}")
    else:
        print("Database schema is up to date.")
