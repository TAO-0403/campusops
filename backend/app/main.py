import logging

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_database_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("campusops")

app = FastAPI(
    title="CampusOps API",
    description="API for the CampusOps campus procurement platform.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
def health_check() -> JSONResponse:
    """Report API availability and the result of a real PostgreSQL connection check."""
    try:
        with psycopg.connect(**get_database_settings()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception:
        logger.warning("Database health check failed.")
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "backend": "ok",
                "database": {
                    "status": "error",
                    "message": "Unable to connect to the database.",
                },
            },
        )

    return JSONResponse(
        content={
            "status": "ok",
            "backend": "ok",
            "database": {"status": "ok", "message": "Connected to PostgreSQL."},
        }
    )
