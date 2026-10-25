# CampusOps

CampusOps is a campus procurement request and approval demonstration built with React, TypeScript, FastAPI, and PostgreSQL.

## Features

- Sign-in, revocable server-side sessions, and requester/administrator permissions.
- Drafts, submission, return, edits, resubmission, approval, and request activity history.
- Server-side search, filters, sorting, pagination, overview metrics and charts, and administrator CSV export.
- Optional PDF quotation uploads in request forms; replacement and deletion on editable requests; authorized viewing and download. Files are limited to 5 MB and stored privately on the local filesystem.
- A transactional database outbox, separate SMTP worker, and failed-delivery retries. Submission and resubmission notify administrators; return and approval notify the applicant.

## Project status

- Demonstration accounts and requests use fictional data. CampusOps has not been used by a school.
- Email notifications have been verified through local Mailpit SMTP only.
- Quotation files currently use private local storage.
- Production deployment, load testing, and long-term operational metrics have not been completed.

## Technology stack

- Frontend: React, TypeScript, Vite
- Backend: Python, FastAPI, Pydantic, psycopg
- Database: PostgreSQL
- Tests: pytest using a separate `campusops_test` database

## Requirements

- Python 3.11
- Node.js 22 and npm
- PostgreSQL 18

## First-time setup

Before starting, use pgAdmin or a local PostgreSQL administrator to create a `campusops_app` login role and an empty `campusops` database owned by that role. Set the role password locally in PostgreSQL; never paste it into source code or documentation.

Create `D:\code\campusops\.env` by copying `.env.example`. Set `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` for that local database (`PGDATABASE=campusops`, `PGUSER=campusops_app`). Keep the database password in this local file only. The driver receives connection fields separately, so password characters do not need URL encoding. The `.env` file is excluded from Git.

```powershell
cd D:\code\campusops
Copy-Item .env.example .env
```

Open `.env` in a local editor and replace only the password placeholder with the PostgreSQL role password. Do not share that file.

In PowerShell:

```powershell
cd D:\code\campusops
python -m venv .venv
cd backend
..\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\.venv\Scripts\python.exe -m app.migrate
..\.venv\Scripts\python.exe -m app.seed_demo
```

Migrations are versioned and applied in order. They add tables and indexes without dropping or recreating the database. The demo seed can be run again safely.

Install frontend dependencies once:

```powershell
cd D:\code\campusops\frontend
npm install
```

## Daily startup

In one PowerShell window:

```powershell
cd D:\code\campusops\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

In a second PowerShell window:

```powershell
cd D:\code\campusops\frontend
npm run dev
```

Open `http://127.0.0.1:5173`. The API health check is at `http://127.0.0.1:8000/api/health`; it runs a real `SELECT 1` query and returns HTTP 503 if PostgreSQL is unavailable. Interactive API documentation is at `http://127.0.0.1:8000/docs`.

## Demo accounts

Run `python -m app.seed_demo` from the `backend` directory to create or refresh these local demo accounts. Demo passwords are separate from the PostgreSQL password.

| Role | Email | Password |
|---|---|---|
| Requester | `alex.morgan@campusops.test` | `Northstar-Applicant-2026!` |
| Requester | `jordan.taylor@campusops.test` | `Riverstone-Applicant-2026!` |
| Administrator | `casey.lee@campusops.test` | `Harbor-Admin-2026!` |

These credentials are for local demonstration only. Passwords are stored as Argon2 hashes.

## Optional showcase requests

The application works with an empty request table. For a fuller local presentation, an optional script can add 25 fictional requests across the two requester accounts, departments, amounts, and all four statuses. It writes matching Created, Submitted, Returned, and Approved history events. It never changes existing users, requests, or history, and repeated runs skip records it previously added.

The script refuses to connect unless the local environment explicitly selects `PGDATABASE=campusops`, a loopback `PGHOST`, and the `campusops_app` role, and the current PowerShell session opts in. Run it manually only after first-time setup and migration:

```powershell
cd D:\code\campusops
$env:CAMPUSOPS_ALLOW_DEMO_DATA = "1"
cd backend
..\.venv\Scripts\python.exe -m app.seed_demo_requests
Remove-Item Env:CAMPUSOPS_ALLOW_DEMO_DATA
```

The script uses the local `.env` database fields and does not print the database password. It is not part of the startup command and does not seed the test database.

## Quotation attachments

Applicants can include an optional PDF (maximum 5 MB) when creating or editing a Draft or Returned request. They can replace or remove it before saving. Administrators and the owning applicant can view or download it when authorized. Files are stored in the private local `data/attachments` directory by default; `CAMPUSOPS_ATTACHMENT_DIR` selects another path. The database stores attachment metadata, not file contents. This storage is local to one host: back up the attachment directory together with PostgreSQL and restore both to the same deployment.

## Email notifications (local Mailpit)

Notifications are disabled by default. For a local Mailpit demonstration, set the following in the local `.env` file:

```dotenv
CAMPUSOPS_EMAIL_ENABLED=true
CAMPUSOPS_SMTP_HOST=127.0.0.1
CAMPUSOPS_SMTP_PORT=1025
CAMPUSOPS_SMTP_USERNAME=
CAMPUSOPS_SMTP_PASSWORD=
CAMPUSOPS_SMTP_TLS=false
CAMPUSOPS_SMTP_SSL=false
CAMPUSOPS_SMTP_TIMEOUT=5
CAMPUSOPS_EMAIL_FROM=notifications@campusops.example.test
CAMPUSOPS_FRONTEND_URL=http://127.0.0.1:5173
```

On Windows, download and extract `mailpit.exe` from the [official Mailpit releases](https://github.com/axllent/mailpit/releases), following the [official installation guide](https://mailpit.axllent.org/docs/install/). Run `.\mailpit.exe`; the local inbox is `http://127.0.0.1:8025` and SMTP listens on `127.0.0.1:1025` by default.

From the `backend` directory, process one queued message with:

```powershell
..\.venv\Scripts\python.exe -m app.send_notifications --once
```

For a local workflow demo, start the worker in foreground polling mode with `..\.venv\Scripts\python.exe -m app.send_notifications --poll-interval 2 --retry-interval 30`. Submit or resubmit a request to notify administrators; return or approve it to notify its applicant. This verifies delivery to Mailpit only, not an external email service. SMTP may redeliver if the server accepts a message but the worker stops before recording success; delivery is not exactly-once.

## Screenshots

[View screenshots](docs/showcase.md)

## Verification

Create an empty PostgreSQL database named `campusops_test` owned by `campusops_app` using a local PostgreSQL administrator. The test suite refuses to run when its configured database matches the development database and only clears request, user, and session data inside the `_test` database. It never clears the development database.

```powershell
cd D:\code\campusops\backend
..\.venv\Scripts\python.exe -m pytest -q
```

Build the frontend with:

```powershell
cd D:\code\campusops\frontend
npm run build
```

## Production considerations

| Available in this demonstration | Work needed before production |
|---|---|
| API role, ownership, and CSRF checks; request status, activity event, and notification outbox are committed together. The SMTP worker claims tasks safely and retries failures. | Production identity and security review; managed secret handling and authenticated TLS SMTP; worker supervision, backlog monitoring, alerting, and retention policies. |
| Quotation downloads are permission-checked and files are outside the public web directory. | Shared durable attachment storage for multiple servers, with coordinated database/file backups and tested restoration. |

The outbox prevents business changes from depending on immediate SMTP availability, but SMTP delivery can still be duplicated at the acceptance/acknowledgement boundary. No production deployment, load test, or long-term reliability measurement has been completed.
