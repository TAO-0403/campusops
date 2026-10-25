import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from psycopg import Connection

from app.db import connect
from app.dependencies import (
    AuthContext,
    get_auth_context,
    require_admin_with_csrf,
    require_requester_with_csrf,
)
from app.schemas import ApprovalInput, RequestInput, ResubmitInput, ReturnInput

router = APIRouter(tags=["purchase requests"])
REQUEST_STATUSES = ("Draft", "Submitted", "Returned", "Approved")
SORT_COLUMNS = {"created_at": "r.created_at", "amount": "r.amount"}


def _serialize_request(row: dict) -> dict:
    result = dict(row)
    result["amount"] = format(result["amount"], ".2f")
    return result


def _get_request(connection: Connection, request_id: int) -> dict | None:
    return connection.execute(
        """
        SELECT r.id, r.title, r.description, r.vendor, r.department_id,
               d.name AS department_name, r.amount, r.currency, r.requester_id,
               u.full_name AS requester_name, r.status, r.created_at, r.updated_at
        FROM purchase_requests AS r
        LEFT JOIN departments AS d ON d.id = r.department_id
        JOIN users AS u ON u.id = r.requester_id
        WHERE r.id = %s
        """,
        (request_id,),
    ).fetchone()


def _record_event(
    connection: Connection,
    request_id: int,
    actor_id: int,
    event_type: str,
    previous_status: str | None,
    new_status: str,
    comment: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO request_events
            (request_id, actor_id, event_type, previous_status, new_status, comment)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (request_id, actor_id, event_type, previous_status, new_status, comment),
    )


def _lock_owned_request(connection: Connection, request_id: int, user_id: int) -> dict:
    row = connection.execute(
        "SELECT id, status FROM purchase_requests WHERE id = %s AND requester_id = %s FOR UPDATE",
        (request_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase request not found.")
    return row


def _require_owned_editable(connection: Connection, request_id: int, user_id: int) -> dict:
    row = _lock_owned_request(connection, request_id, user_id)
    if row["status"] not in ("Draft", "Returned"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft or returned requests can be edited.")
    return row


def _require_status(row: dict, expected: str) -> None:
    if row["status"] != expected:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Only {expected.lower()} requests can use this action.")


def _validate_department(connection: Connection, department_id: int | None) -> None:
    if department_id is None:
        return
    exists = connection.execute("SELECT 1 FROM departments WHERE id = %s", (department_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose a valid department.")


def _values(payload: RequestInput) -> tuple:
    return (
        payload.title.strip(),
        payload.description.strip(),
        payload.vendor.strip(),
        payload.department_id,
        payload.amount,
    )


def _serialize_events(connection: Connection, request_id: int) -> list[dict]:
    return connection.execute(
        """
        SELECT e.id, e.event_type, e.previous_status, e.new_status, e.details, e.comment,
               e.created_at, u.full_name AS actor_name
        FROM request_events AS e
        JOIN users AS u ON u.id = e.actor_id
        WHERE e.request_id = %s
        ORDER BY e.id
        """,
        (request_id,),
    ).fetchall()


@router.get("/departments", tags=["departments"])
def list_departments(_: AuthContext = Depends(get_auth_context)) -> list[dict]:
    with connect() as connection:
        return connection.execute("SELECT id, code, name FROM departments ORDER BY name").fetchall()


@router.get("/requests")
def list_requests(
    search: str | None = Query(default=None, max_length=120),
    request_status: Literal["Draft", "Submitted", "Returned", "Approved"] | None = Query(default=None, alias="status"),
    department_id: int | None = Query(default=None, gt=0),
    sort_by: Literal["created_at", "amount"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=20, multiple_of=10),
    context: AuthContext = Depends(get_auth_context),
) -> dict:
    clauses, parameters = _request_filters(context, search, request_status, department_id)
    where_sql = " AND ".join(clauses)
    order_column = SORT_COLUMNS[sort_by]
    direction = "ASC" if sort_order == "asc" else "DESC"
    offset = (page - 1) * page_size
    with connect() as connection:
        total = connection.execute(
            f"SELECT count(*) AS total FROM purchase_requests AS r WHERE {where_sql}", parameters
        ).fetchone()["total"]
        rows = connection.execute(
            f"""
            SELECT r.id, r.title, r.vendor, r.department_id, d.name AS department_name,
                   r.amount, r.currency, r.status, r.requester_id,
                   u.full_name AS requester_name, r.created_at, r.updated_at
            FROM purchase_requests AS r
            LEFT JOIN departments AS d ON d.id = r.department_id
            JOIN users AS u ON u.id = r.requester_id
            WHERE {where_sql}
            ORDER BY {order_column} {direction}, r.id {direction}
            LIMIT %s OFFSET %s
            """,
            (*parameters, page_size, offset),
        ).fetchall()
    return {"items": [_serialize_request(row) for row in rows], "total": total, "page": page, "page_size": page_size}


CSV_HEADERS = (
    "Request ID",
    "Title",
    "Applicant",
    "Department",
    "Vendor",
    "Amount (USD)",
    "Status",
    "Created At",
    "Updated At",
)


def _csv_text(value: str | None) -> str:
    text = value or ""
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _csv_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


@router.get("/requests/export.csv")
def export_requests_csv(
    search: str | None = Query(default=None, max_length=120),
    request_status: Literal["Draft", "Submitted", "Returned", "Approved"] | None = Query(default=None, alias="status"),
    department_id: int | None = Query(default=None, gt=0),
    sort_by: Literal["created_at", "amount"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
    context: AuthContext = Depends(get_auth_context),
) -> Response:
    if context.user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can export purchase requests.")

    clauses, parameters = _request_filters(context, search, request_status, department_id)
    where_sql = " AND ".join(clauses)
    order_column = SORT_COLUMNS[sort_by]
    direction = "ASC" if sort_order == "asc" else "DESC"
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT r.id, r.title, u.full_name AS requester_name, d.name AS department_name,
                   r.vendor, r.amount, r.status, r.created_at, r.updated_at
            FROM purchase_requests AS r
            LEFT JOIN departments AS d ON d.id = r.department_id
            JOIN users AS u ON u.id = r.requester_id
            WHERE {where_sql}
            ORDER BY {order_column} {direction}, r.id {direction}
            """,
            parameters,
        ).fetchall()

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(CSV_HEADERS)
    for row in rows:
        writer.writerow(
            (
                row["id"],
                _csv_text(row["title"]),
                _csv_text(row["requester_name"]),
                _csv_text(row["department_name"]),
                _csv_text(row["vendor"]),
                format(row["amount"], ".2f"),
                row["status"],
                _csv_timestamp(row["created_at"]),
                _csv_timestamp(row["updated_at"]),
            )
        )

    filename = f"campusops-requests-{datetime.now(timezone.utc):%Y-%m-%d}.csv"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _request_filters(
    context: AuthContext,
    search: str | None,
    request_status: str | None,
    department_id: int | None,
) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    parameters: list[object] = []
    if context.user["role"] != "admin":
        clauses.append("r.requester_id = %s")
        parameters.append(context.user["id"])
    if search and search.strip():
        clauses.append("r.title ILIKE %s")
        parameters.append(f"%{search.strip()}%")
    if request_status:
        clauses.append("r.status = %s")
        parameters.append(request_status)
    if department_id is not None:
        clauses.append("r.department_id = %s")
        parameters.append(department_id)
    return clauses or ["TRUE"], parameters


@router.get("/requests/overview")
def request_overview(
    search: str | None = Query(default=None, max_length=120),
    request_status: Literal["Draft", "Submitted", "Returned", "Approved"] | None = Query(default=None, alias="status"),
    department_id: int | None = Query(default=None, gt=0),
    context: AuthContext = Depends(get_auth_context),
) -> dict:
    clauses, parameters = _request_filters(context, search, request_status, department_id)
    where_sql = " AND ".join(clauses)
    with connect() as connection:
        status_rows = connection.execute(
            f"SELECT r.status, count(*) AS count FROM purchase_requests AS r WHERE {where_sql} GROUP BY r.status",
            parameters,
        ).fetchall()
        department_rows = connection.execute(
            f"""
            SELECT r.department_id, d.name AS department_name, count(*) AS count
            FROM purchase_requests AS r
            LEFT JOIN departments AS d ON d.id = r.department_id
            WHERE {where_sql}
            GROUP BY r.department_id, d.name
            ORDER BY d.name NULLS LAST, r.department_id
            """,
            parameters,
        ).fetchall()
        amount_row = connection.execute(
            f"""
            SELECT count(*) AS total_requests,
                   count(*) FILTER (WHERE r.status = 'Submitted') AS pending_review,
                   count(*) FILTER (WHERE r.status = 'Returned') AS changes_requested,
                   COALESCE(sum(r.amount) FILTER (WHERE r.status = 'Approved'), 0)::numeric(14, 2) AS approved_amount
            FROM purchase_requests AS r
            WHERE {where_sql}
            """,
            parameters,
        ).fetchone()

    counts = {row["status"]: row["count"] for row in status_rows}
    return {
        "total_requests": amount_row["total_requests"],
        "pending_review": amount_row["pending_review"],
        "changes_requested": amount_row["changes_requested"],
        "approved_amount": format(amount_row["approved_amount"], ".2f"),
        "requests_by_status": [{"status": value, "count": counts.get(value, 0)} for value in REQUEST_STATUSES],
        "requests_by_department": department_rows,
    }


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(
    payload: RequestInput,
    context: AuthContext = Depends(require_requester_with_csrf),
) -> dict:
    with connect() as connection:
        _validate_department(connection, payload.department_id)
        row = connection.execute(
            """
            INSERT INTO purchase_requests
                (title, description, vendor, department_id, amount, currency, requester_id)
            VALUES (%s, %s, %s, %s, %s, 'USD', %s)
            RETURNING id
            """,
            (*_values(payload), context.user["id"]),
        ).fetchone()
        _record_event(connection, row["id"], context.user["id"], "Created", None, "Draft")
        result = _get_request(connection, row["id"])
    return _serialize_request(result)


@router.get("/requests/{request_id}")
def get_request(request_id: int, context: AuthContext = Depends(get_auth_context)) -> dict:
    with connect() as connection:
        row = _get_request(connection, request_id)
        if row is None or (
            context.user["role"] != "admin" and row["requester_id"] != context.user["id"]
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase request not found.")
        result = _serialize_request(row)
        result["events"] = _serialize_events(connection, request_id)
    return result


@router.put("/requests/{request_id}")
def update_request(
    request_id: int,
    payload: RequestInput,
    context: AuthContext = Depends(require_requester_with_csrf),
) -> dict:
    with connect() as connection:
        existing = _require_owned_editable(connection, request_id, context.user["id"])
        _validate_department(connection, payload.department_id)
        connection.execute(
            """
            UPDATE purchase_requests
            SET title = %s, description = %s, vendor = %s, department_id = %s,
                amount = %s, updated_at = now()
            WHERE id = %s
            """,
            (*_values(payload), request_id),
        )
        _record_event(connection, request_id, context.user["id"], "Updated", existing["status"], existing["status"])
        result = _get_request(connection, request_id)
    return _serialize_request(result)


@router.post("/requests/{request_id}/submit")
def submit_request(
    request_id: int,
    context: AuthContext = Depends(require_requester_with_csrf),
) -> dict:
    with connect() as connection:
        existing = _lock_owned_request(connection, request_id, context.user["id"])
        _require_status(existing, "Draft")
        row = _get_request(connection, request_id)
        missing_fields = []
        for field, label in (
            ("title", "title"),
            ("description", "description"),
            ("vendor", "vendor"),
        ):
            if not row[field].strip():
                missing_fields.append(label)
        if row["department_id"] is None:
            missing_fields.append("department")
        if Decimal(row["amount"]) <= 0:
            missing_fields.append("an amount greater than zero")
        if missing_fields:
            joined = ", ".join(missing_fields)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Complete the required fields before submitting: {joined}.",
            )

        connection.execute(
            "UPDATE purchase_requests SET status = 'Submitted', updated_at = now() WHERE id = %s",
            (request_id,),
        )
        _record_event(connection, request_id, context.user["id"], "Submitted", "Draft", "Submitted")
        result = _get_request(connection, request_id)
    return _serialize_request(result)


def _validate_ready_for_submission(row: dict) -> None:
    missing_fields = []
    for field, label in (("title", "title"), ("description", "description"), ("vendor", "vendor")):
        if not row[field].strip():
            missing_fields.append(label)
    if row["department_id"] is None:
        missing_fields.append("department")
    if Decimal(row["amount"]) <= 0:
        missing_fields.append("an amount greater than zero")
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Complete the required fields before submitting: {joined}.")


@router.post("/requests/{request_id}/approve")
def approve_request(
    request_id: int,
    payload: ApprovalInput,
    context: AuthContext = Depends(require_admin_with_csrf),
) -> dict:
    with connect() as connection:
        row = connection.execute(
            "SELECT id, status FROM purchase_requests WHERE id = %s FOR UPDATE", (request_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase request not found.")
        _require_status(row, "Submitted")
        connection.execute("UPDATE purchase_requests SET status = 'Approved', updated_at = now() WHERE id = %s", (request_id,))
        _record_event(connection, request_id, context.user["id"], "Approved", "Submitted", "Approved", payload.comment.strip() or None)
        result = _get_request(connection, request_id)
    return _serialize_request(result)


@router.post("/requests/{request_id}/return")
def return_request(
    request_id: int,
    payload: ReturnInput,
    context: AuthContext = Depends(require_admin_with_csrf),
) -> dict:
    with connect() as connection:
        row = connection.execute(
            "SELECT id, status FROM purchase_requests WHERE id = %s FOR UPDATE", (request_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase request not found.")
        _require_status(row, "Submitted")
        connection.execute("UPDATE purchase_requests SET status = 'Returned', updated_at = now() WHERE id = %s", (request_id,))
        _record_event(connection, request_id, context.user["id"], "Returned", "Submitted", "Returned", payload.reason)
        result = _get_request(connection, request_id)
    return _serialize_request(result)


@router.post("/requests/{request_id}/resubmit")
def resubmit_request(
    request_id: int,
    payload: ResubmitInput,
    context: AuthContext = Depends(require_requester_with_csrf),
) -> dict:
    with connect() as connection:
        row = _lock_owned_request(connection, request_id, context.user["id"])
        _require_status(row, "Returned")
        request_row = _get_request(connection, request_id)
        _validate_ready_for_submission(request_row)
        connection.execute("UPDATE purchase_requests SET status = 'Submitted', updated_at = now() WHERE id = %s", (request_id,))
        _record_event(connection, request_id, context.user["id"], "Resubmitted", "Returned", "Submitted", payload.comment.strip() or None)
        result = _get_request(connection, request_id)
    return _serialize_request(result)
