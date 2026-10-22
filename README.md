# CampusOps

CampusOps is a campus procurement workspace built with React, TypeScript, FastAPI, and PostgreSQL. Applicants can save, edit, and submit purchase requests. Administrators can review all requests and their activity history.

## Requirements

- Python 3.11
- Node.js 22 and npm
- PostgreSQL 18

## First-time setup

Create `D:\code\campusops\.env` by copying `.env.example`. Set `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` to your local PostgreSQL connection values. Keep the database password in this local file only. The driver receives connection fields separately, so password characters do not need URL encoding. The `.env` file is excluded from Git.

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

## Request review workflow

Applicants can save and edit a draft, then submit it for review. Submitted requests are locked while an administrator reviews them. An administrator can approve a request with an optional comment or return it with a required reason. The applicant can edit a returned request; edits keep it in Returned until the applicant explicitly resubmits it. Every submission, resubmission, return, and approval is recorded with its actor, timestamp, status transition, and comment when provided.

To try the full workflow, sign in as Alex, create and submit a request, then sign out. Sign in as Casey and open the submitted request to approve it or return it with a reason. To complete the return path, sign back in as Alex, edit the returned request, save the changes, and use **Resubmit for review**. Sign in as Casey again to approve the resubmitted request. Activity history appears on the request detail page.

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

## Current scope

Authentication, request drafts, submission, administrator approval and return, returned-request editing and resubmission, and activity history are included. Analytics, attachments, notifications, and deployment are not included.
