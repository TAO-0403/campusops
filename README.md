# CampusOps

CampusOps is a campus procurement workspace built with React, TypeScript, FastAPI, and PostgreSQL. This first stage provides a landing page and a live backend and database health check.

## Requirements

- Python 3.11
- Node.js 22 and npm
- PostgreSQL 18 with a local `campusops` database and `campusops_app` role

## Configure the database

Create `D:\code\campusops\.env` by copying `.env.example`. Set `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD` to your local PostgreSQL connection values. Enter your database password only in this local file. Passwords are passed as a separate driver field, so special characters do not need URL encoding. The `.env` file is excluded from Git.

## Start the backend

In PowerShell, from the project directory:

```powershell
cd D:\code\campusops
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

The API health check is available at `http://127.0.0.1:8000/api/health`. Interactive API documentation is available at `http://127.0.0.1:8000/docs`. The check runs a real `SELECT 1` query and returns HTTP 503 when PostgreSQL is unreachable.

## Start the frontend

Open a second PowerShell window:

```powershell
cd D:\code\campusops\frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173` to view the CampusOps home page and live service status.

## Build the frontend

```powershell
cd D:\code\campusops\frontend
npm run build
```

## Current scope

The first stage does not include authentication, purchase requests, approvals, activity history, analytics, or deployment.
