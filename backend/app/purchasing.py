from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
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
        ORDER BY e.created_at, e.id
        """,
        (request_id,),
    ).fetchall()


@router.get("/departments", tags=["departments"])
def list_departments(_: AuthContext = Depends(get_auth_context)) -> list[dict]:
    with connect() as connection:
        return connection.execute("SELECT id, code, name FROM departments ORDER BY name").fetchall()


@router.get("/requests")
def list_requests(context: AuthContext = Depends(get_auth_context)) -> list[dict]:
    with connect() as connection:
        if context.user["role"] == "admin":
            rows = connection.execute(
                """
                SELECT r.id, r.title, r.vendor, r.department_id, d.name AS department_name,
                       r.amount, r.currency, r.status, r.requester_id,
                       u.full_name AS requester_name, r.created_at, r.updated_at
                FROM purchase_requests AS r
                LEFT JOIN departments AS d ON d.id = r.department_id
                JOIN users AS u ON u.id = r.requester_id
                ORDER BY r.updated_at DESC, r.id DESC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT r.id, r.title, r.vendor, r.department_id, d.name AS department_name,
                       r.amount, r.currency, r.status, r.requester_id,
                       u.full_name AS requester_name, r.created_at, r.updated_at
                FROM purchase_requests AS r
                LEFT JOIN departments AS d ON d.id = r.department_id
                JOIN users AS u ON u.id = r.requester_id
                WHERE r.requester_id = %s
                ORDER BY r.updated_at DESC, r.id DESC
                """,
                (context.user["id"],),
            ).fetchall()
    return [_serialize_request(row) for row in rows]


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
