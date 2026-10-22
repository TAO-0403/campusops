import psycopg
from psycopg.rows import dict_row

from app.config import get_database_settings


def connect(database: str | None = None) -> psycopg.Connection:
    return psycopg.connect(**get_database_settings(database), row_factory=dict_row)
