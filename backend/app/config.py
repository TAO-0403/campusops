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


def get_attachment_storage_dir() -> Path:
    """Return the private local directory used for quotation attachments."""
    configured_path = os.getenv("CAMPUSOPS_ATTACHMENT_DIR")
    if configured_path:
        path = Path(configured_path).expanduser()
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
    return PROJECT_ROOT / "data" / "attachments"


def email_notifications_enabled() -> bool:
    return os.getenv("CAMPUSOPS_EMAIL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def get_smtp_settings() -> dict[str, str | int | bool]:
    return {
        "host": os.getenv("CAMPUSOPS_SMTP_HOST", "127.0.0.1"),
        "port": int(os.getenv("CAMPUSOPS_SMTP_PORT", "1025")),
        "username": os.getenv("CAMPUSOPS_SMTP_USERNAME", ""),
        "password": os.getenv("CAMPUSOPS_SMTP_PASSWORD", ""),
        "use_tls": os.getenv("CAMPUSOPS_SMTP_TLS", "false").strip().lower() in {"1", "true", "yes", "on"},
        "use_ssl": os.getenv("CAMPUSOPS_SMTP_SSL", "false").strip().lower() in {"1", "true", "yes", "on"},
        "timeout": int(os.getenv("CAMPUSOPS_SMTP_TIMEOUT", "5")),
        "sender": os.getenv("CAMPUSOPS_EMAIL_FROM", "CampusOps <notifications@campusops.example.test>"),
    }


def get_frontend_base_url() -> str:
    return os.getenv("CAMPUSOPS_FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")
