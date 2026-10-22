"""Add a repeatable set of fictional requests to the explicitly selected local demo database."""

import os
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from app.db import connect

SHOWCASE_STATUSES = (
    "Draft", "Submitted", "Returned", "Approved", "Submitted",
    "Draft", "Approved", "Returned", "Submitted", "Approved",
    "Draft", "Returned", "Approved", "Submitted", "Draft",
    "Approved", "Submitted", "Returned", "Draft", "Approved",
    "Submitted", "Returned", "Approved", "Draft", "Submitted",
)

TITLES = (
    "Chemistry lab safety goggles", "Library study room chairs", "Student orientation banners",
    "Biology microscope slides", "Campus maintenance tool set", "Digital archives scanner",
    "Environmental science sensors", "Residence hall first aid kits", "Lecture hall microphones",
    "Fine arts paper and canvas", "Research sample storage boxes", "Library barcode readers",
    "Campus event folding tables", "Physics lab power supplies", "Student services desk signage",
    "Facilities replacement filters", "Nursing simulation supplies", "Media lab headphones",
    "Chemistry glassware set", "Campus map display boards", "Library reference books",
    "Outdoor classroom benches", "Robotics club components", "Athletics water stations",
    "Administrative office monitors",
)

DEPARTMENT_CODES = ("SCI", "LIB", "STU", "OPS")
REQUESTER_EMAILS = ("alex.morgan@campusops.test", "jordan.taylor@campusops.test")
ADMIN_EMAIL = "casey.lee@campusops.test"


def _sample_event_timestamps(now: datetime, index: int) -> tuple[datetime, datetime, datetime]:
    created_at = now - timedelta(days=len(TITLES) - index)
    submitted_at = created_at + timedelta(hours=2)
    decision_at = submitted_at + timedelta(hours=3)
    return created_at, submitted_at, decision_at


def _require_explicit_local_database() -> None:
    if os.getenv("CAMPUSOPS_ALLOW_DEMO_DATA") != "1":
        raise SystemExit("Set CAMPUSOPS_ALLOW_DEMO_DATA=1 in this PowerShell session to enable demo data seeding.")

    if os.getenv("PGDATABASE") != "campusops":
        raise SystemExit("Demo requests can only be added when PGDATABASE is explicitly set to campusops.")

    host = os.getenv("PGHOST", "").strip().lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Demo requests can only be added to a loopback PostgreSQL host.")

    if os.getenv("PGUSER") != "campusops_app":
        raise SystemExit("Demo requests require the campusops_app database role.")


def seed_demo_requests() -> int:
    _require_explicit_local_database()
    now = datetime.now(timezone.utc)
    inserted = 0

    with connect() as connection:
        database_name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        if database_name != "campusops":
            raise SystemExit("Connected database does not match the explicitly allowed campusops database.")

        migration_table = connection.execute("SELECT to_regclass('public.schema_migrations') AS name").fetchone()["name"]
        if migration_table is None:
            raise SystemExit("Apply project database migrations before adding showcase requests.")
        migration_exists = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = %s",
            ("003_approval_workflow.sql",),
        ).fetchone()
        if migration_exists is None:
            raise SystemExit("Apply project database migrations before adding showcase requests.")

        connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("campusops_showcase_requests_v1",))
        departments = {
            row["code"]: row["id"]
            for row in connection.execute("SELECT id, code FROM departments").fetchall()
        }
        user_rows = connection.execute(
            "SELECT id, email, role FROM users WHERE email = ANY(%s) AND active = TRUE",
            ([*REQUESTER_EMAILS, ADMIN_EMAIL],),
        ).fetchall()
        users = {row["email"]: row["id"] for row in user_rows}
        user_roles = {row["email"]: row["role"] for row in user_rows}
        if not set(DEPARTMENT_CODES).issubset(departments):
            raise SystemExit("Expected demo departments are missing; apply project database migrations first.")
        if not set(REQUESTER_EMAILS).issubset(users) or ADMIN_EMAIL not in users:
            raise SystemExit("Run the demo account seed before adding showcase requests.")
        if any(user_roles[email] != "requester" for email in REQUESTER_EMAILS) or user_roles[ADMIN_EMAIL] != "admin":
            raise SystemExit("Demo accounts have unexpected roles; review the local demo account seed first.")

        for index, title in enumerate(TITLES):
            seed_key = f"campusops-showcase-v1-{index + 1:03d}"
            exists = connection.execute(
                "SELECT 1 FROM request_events WHERE event_type = 'Created' AND details ->> 'demo_batch_key' = %s",
                (seed_key,),
            ).fetchone()
            if exists:
                continue

            requester_id = users[REQUESTER_EMAILS[index % len(REQUESTER_EMAILS)]]
            department_id = departments[DEPARTMENT_CODES[index % len(DEPARTMENT_CODES)]]
            amount = f"{125 + index * 73}.{(index * 37) % 100:02d}"
            created_at, submitted_at, decision_at = _sample_event_timestamps(now, index)
            final_status = SHOWCASE_STATUSES[index]

            request = connection.execute(
                """
                INSERT INTO purchase_requests
                    (title, description, vendor, department_id, amount, currency, requester_id, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'USD', %s, 'Draft', %s, %s)
                RETURNING id
                """,
                (
                    title,
                    f"Fictional showcase request {index + 1:02d} for a campus procurement workflow demonstration.",
                    f"Campus Demo Supplier {(index % 6) + 1}",
                    department_id,
                    amount,
                    requester_id,
                    created_at,
                    created_at,
                ),
            ).fetchone()
            request_id = request["id"]
            connection.execute(
                """
                INSERT INTO request_events
                    (request_id, actor_id, event_type, previous_status, new_status, details, created_at)
                VALUES (%s, %s, 'Created', NULL, 'Draft', %s, %s)
                """,
                (request_id, requester_id, Jsonb({"demo_batch_key": seed_key, "source": "fictional_showcase"}), created_at),
            )

            if final_status == "Draft":
                inserted += 1
                continue

            connection.execute(
                "UPDATE purchase_requests SET status = 'Submitted', updated_at = %s WHERE id = %s",
                (submitted_at, request_id),
            )
            connection.execute(
                """
                INSERT INTO request_events (request_id, actor_id, event_type, previous_status, new_status, created_at)
                VALUES (%s, %s, 'Submitted', 'Draft', 'Submitted', %s)
                """,
                (request_id, requester_id, submitted_at),
            )

            if final_status in ("Returned", "Approved"):
                comment = "Please add a little more detail for this fictional example." if final_status == "Returned" else "Approved for the fictional showcase."
                connection.execute(
                    "UPDATE purchase_requests SET status = %s, updated_at = %s WHERE id = %s",
                    (final_status, decision_at, request_id),
                )
                connection.execute(
                    """
                    INSERT INTO request_events
                        (request_id, actor_id, event_type, previous_status, new_status, comment, created_at)
                    VALUES (%s, %s, %s, 'Submitted', %s, %s, %s)
                    """,
                    (request_id, users[ADMIN_EMAIL], final_status, final_status, comment, decision_at),
                )

            inserted += 1

    return inserted


if __name__ == "__main__":
    count = seed_demo_requests()
    print(f"Added {count} fictional showcase requests. Existing showcase records were left unchanged.")
