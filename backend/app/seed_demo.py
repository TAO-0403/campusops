from app.db import connect
from app.migrate import apply_migrations
from app.security import hash_password

DEMO_USERS = (
    {
        "email": "alex.morgan@campusops.test",
        "full_name": "Alex Morgan",
        "role": "requester",
        "department_code": "SCI",
        "password": "Northstar-Applicant-2026!",
    },
    {
        "email": "jordan.taylor@campusops.test",
        "full_name": "Jordan Taylor",
        "role": "requester",
        "department_code": "LIB",
        "password": "Riverstone-Applicant-2026!",
    },
    {
        "email": "casey.lee@campusops.test",
        "full_name": "Casey Lee",
        "role": "admin",
        "department_code": None,
        "password": "Harbor-Admin-2026!",
    },
)


def seed_demo_users(database: str | None = None) -> None:
    apply_migrations(database)
    with connect(database) as connection:
        for demo_user in DEMO_USERS:
            department_id = None
            if demo_user["department_code"]:
                department = connection.execute(
                    "SELECT id FROM departments WHERE code = %s",
                    (demo_user["department_code"],),
                ).fetchone()
                department_id = department["id"]

            connection.execute(
                """
                INSERT INTO users (email, full_name, role, department_id, password_hash)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    role = EXCLUDED.role,
                    department_id = EXCLUDED.department_id,
                    password_hash = EXCLUDED.password_hash,
                    active = TRUE
                """,
                (
                    demo_user["email"],
                    demo_user["full_name"],
                    demo_user["role"],
                    department_id,
                    hash_password(demo_user["password"]),
                ),
            )


if __name__ == "__main__":
    seed_demo_users()
    print("Demo users are ready.")
