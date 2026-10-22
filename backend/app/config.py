import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def get_database_settings(database: str | None = None) -> dict[str, str | int]:
    """Read database fields independently so special password characters stay intact."""
    return {
        "host": os.getenv("PGHOST", "127.0.0.1"),
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": database or os.getenv("PGDATABASE", "campusops"),
        "user": os.getenv("PGUSER", "campusops_app"),
        "password": os.getenv("PGPASSWORD", ""),
        "connect_timeout": 3,
    }
