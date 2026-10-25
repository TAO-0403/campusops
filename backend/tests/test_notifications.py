from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient
import pytest

from app import notifications, purchasing
from app.db import connect
from app.main import app

APPLICANT_EMAIL = "alex.morgan@campusops.test"
APPLICANT_PASSWORD = "Northstar-Applicant-2026!"
ADMIN_EMAIL = "casey.lee@campusops.test"
ADMIN_PASSWORD = "Harbor-Admin-2026!"


def _sign_in(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _create_request(client: TestClient, csrf: str, **overrides: object) -> dict:
    department_id = next(row["id"] for row in client.get("/api/departments").json() if row["code"] == "SCI")
    payload = {
        "title": "Lab purchase",
        "description": "For the teaching laboratory.",
        "vendor": "Example Supplies",
        "department_id": department_id,
        "amount": "123.45",
        **overrides,
    }
    response = client.post("/api/requests", json=payload, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 201
    return response.json()


def _outbox(request_id: int) -> list[dict]:
    with connect() as connection:
        return connection.execute(
            """
            SELECT outbox.*, users.email AS current_email, users.role AS recipient_role
            FROM email_outbox AS outbox
            JOIN request_events AS events ON events.id = outbox.request_event_id
            JOIN users ON users.id = outbox.recipient_user_id
            WHERE events.request_id = %s
            ORDER BY events.id, users.id
            """,
            (request_id,),
        ).fetchall()


def _submit(client: TestClient, request_id: int, csrf: str):
    return client.post(f"/api/requests/{request_id}/submit", headers={"X-CSRF-Token": csrf})


def _minimal_pdf() -> bytes:
    chunks = [b"%PDF-1.4\n"]
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [] /Count 0 >>"]
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(sum(map(len, chunks)))
        chunks.append(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = sum(map(len, chunks))
    chunks.append(b"xref\n0 3\n0000000000 65535 f \n")
    chunks.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    chunks.append(
        b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return b"".join(chunks)


def test_state_transitions_queue_role_based_notifications_with_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "true")
    monkeypatch.setenv("CAMPUSOPS_FRONTEND_URL", "http://127.0.0.1:5173/")
    with TestClient(app) as applicant:
        applicant_csrf = _sign_in(applicant, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        request = _create_request(applicant, applicant_csrf, title='<script>alert("x")</script> & supplies')
        request_id = request["id"]
        assert _submit(applicant, request_id, applicant_csrf).status_code == 200

    with TestClient(app) as admin:
        admin_csrf = _sign_in(admin, ADMIN_EMAIL, ADMIN_PASSWORD)
        returned = admin.post(
            f"/api/requests/{request_id}/return",
            json={"reason": "Please clarify <b>the purpose</b> & timing."},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert returned.status_code == 200

    with TestClient(app) as applicant:
        applicant_csrf = _sign_in(applicant, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        assert applicant.post(
            f"/api/requests/{request_id}/resubmit",
            json={"comment": "Updated the details."},
            headers={"X-CSRF-Token": applicant_csrf},
        ).status_code == 200

    with TestClient(app) as admin:
        admin_csrf = _sign_in(admin, ADMIN_EMAIL, ADMIN_PASSWORD)
        approved = admin.post(
            f"/api/requests/{request_id}/approve",
            json={"comment": "Approved <after review>."},
            headers={"X-CSRF-Token": admin_csrf},
        )
        assert approved.status_code == 200

    rows = _outbox(request_id)
    assert [row["status"] for row in rows] == ["pending"] * 4
    assert [row["recipient_role"] for row in rows] == ["admin", "requester", "admin", "requester"]
    assert [row["current_email"] for row in rows] == [ADMIN_EMAIL, APPLICANT_EMAIL, ADMIN_EMAIL, APPLICANT_EMAIL]
    assert "Request #" + str(request_id) in rows[0]["text_body"]
    assert '<script>alert("x")</script> & supplies' in rows[0]["text_body"]
    assert "$123.45 USD" in rows[0]["text_body"]
    assert "Department: Science" in rows[0]["text_body"]
    assert f"http://127.0.0.1:5173/requests/{request_id}" in rows[0]["text_body"]
    assert f'href="http://127.0.0.1:5173/requests/{request_id}"' in rows[0]["html_body"]
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; supplies" in rows[0]["html_body"]
    assert "<script>" not in rows[0]["html_body"]
    assert "Please clarify &lt;b&gt;the purpose&lt;/b&gt; &amp; timing." in rows[1]["html_body"]
    assert "Approved &lt;after review&gt;." in rows[3]["html_body"]
    assert "Request submitted for review" in rows[0]["subject"]
    assert "Request resubmitted for review" in rows[2]["subject"]
    assert "Return reason:" in rows[1]["text_body"]
    assert "Approval comment:" in rows[3]["text_body"]


def test_draft_edit_and_attachment_operations_do_not_queue_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "true")
    valid_pdf = _minimal_pdf()
    with TestClient(app) as client:
        csrf = _sign_in(client, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        request = _create_request(client, csrf)
        assert client.put(
            f"/api/requests/{request['id']}",
            json={"title": "Edited draft", "description": "For the teaching laboratory.", "vendor": "Example Supplies", "department_id": request["department_id"], "amount": "123.45"},
            headers={"X-CSRF-Token": csrf},
        ).status_code == 200
        upload = client.post(
            f"/api/requests/{request['id']}/attachment",
            files={"file": ("quote.pdf", valid_pdf, "application/pdf")},
            headers={"X-CSRF-Token": csrf},
        )
        assert upload.status_code == 200
        assert client.delete(f"/api/requests/{request['id']}/attachment", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert _outbox(request["id"]) == []


def test_notifications_disabled_and_invalid_or_failed_transitions_enqueue_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "true")
    with TestClient(app) as applicant:
        csrf = _sign_in(applicant, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        incomplete = _create_request(applicant, csrf, title="", description="", vendor="", department_id=None, amount="0.00")
        assert _submit(applicant, incomplete["id"], csrf).status_code == 422
        complete = _create_request(applicant, csrf)
        assert _submit(applicant, complete["id"], csrf).status_code == 200
        assert _submit(applicant, complete["id"], csrf).status_code == 409
        with connect() as connection:
            assert connection.execute("SELECT count(*) AS count FROM email_outbox").fetchone()["count"] == 1

    # A disabled installation still records its business event but does not enqueue mail.
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "false")
    with TestClient(app) as applicant:
        csrf = _sign_in(applicant, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        disabled_request = _create_request(applicant, csrf)
        assert _submit(applicant, disabled_request["id"], csrf).status_code == 200
    assert _outbox(disabled_request["id"]) == []
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "false")
    assert notifications.process_one_notification() == "disabled"
    with connect() as connection:
        assert connection.execute("SELECT count(*) AS count FROM email_outbox WHERE status = 'pending'").fetchone()["count"] == 1


def test_outbox_insert_rolls_back_with_status_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "true")
    with TestClient(app, raise_server_exceptions=False) as client:
        csrf = _sign_in(client, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        request = _create_request(client, csrf)
        monkeypatch.setattr(purchasing, "enqueue_request_notification", lambda *args: (_ for _ in ()).throw(RuntimeError("outbox failure")))
        response = client.post(
            f"/api/requests/{request['id']}/submit",
            headers={"X-CSRF-Token": csrf},
            follow_redirects=False,
        )
    assert response.status_code == 500
    with connect() as connection:
        state = connection.execute("SELECT status FROM purchase_requests WHERE id = %s", (request["id"],)).fetchone()
        event_count = connection.execute(
            "SELECT count(*) AS count FROM request_events WHERE request_id = %s AND event_type = 'Submitted'",
            (request["id"],),
        ).fetchone()["count"]
    assert state["status"] == "Draft"
    assert event_count == 0
    assert _outbox(request["id"]) == []


def test_same_business_event_and_recipient_cannot_be_enqueued_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "true")
    with TestClient(app) as client:
        csrf = _sign_in(client, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        request = _create_request(client, csrf)
        assert _submit(client, request["id"], csrf).status_code == 200
    with connect() as connection:
        event = connection.execute(
            "SELECT id FROM request_events WHERE request_id = %s AND event_type = 'Submitted'",
            (request["id"],),
        ).fetchone()
        request_row = purchasing._get_request(connection, request["id"])
        assert notifications.enqueue_request_notification(connection, event["id"], request_row, "Submitted", None) == 0
    assert len(_outbox(request["id"])) == 1


def test_smtp_failure_retries_without_rolling_back_and_sent_rows_are_not_resent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "true")
    with TestClient(app) as client:
        csrf = _sign_in(client, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        request = _create_request(client, csrf)
        assert _submit(client, request["id"], csrf).status_code == 200

    monkeypatch.setattr(notifications, "_deliver_email", lambda row: (_ for _ in ()).throw(ConnectionError("private host/password detail")))
    assert notifications.process_one_notification(retry_seconds=1) == "failed"
    failed = _outbox(request["id"])[0]
    assert failed["status"] == "pending"
    assert failed["attempt_count"] == 1
    assert failed["last_error"] == "SMTP delivery failed (ConnectionError)."
    with connect() as connection:
        state = connection.execute("SELECT status FROM purchase_requests WHERE id = %s", (request["id"],)).fetchone()
        connection.execute("UPDATE email_outbox SET next_attempt_at = now() WHERE id = %s", (failed["id"],))
    assert state["status"] == "Submitted"

    delivered = []
    monkeypatch.setattr(notifications, "_deliver_email", lambda row: delivered.append(row["id"]))
    assert notifications.process_one_notification() == "sent"
    assert delivered == [failed["id"]]
    sent = _outbox(request["id"])[0]
    assert sent["status"] == "sent" and sent["sent_at"] is not None
    assert sent["attempt_count"] == 2 and sent["last_error"] is None
    assert notifications.process_one_notification() == "empty"
    assert delivered == [failed["id"]]


def test_parallel_workers_do_not_deliver_the_same_claimed_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPUSOPS_EMAIL_ENABLED", "true")
    with TestClient(app) as client:
        csrf = _sign_in(client, APPLICANT_EMAIL, APPLICANT_PASSWORD)
        request = _create_request(client, csrf)
        assert _submit(client, request["id"], csrf).status_code == 200

    entered_send, release_send = Event(), Event()
    deliveries: list[int] = []

    def blocked_delivery(row: dict) -> None:
        deliveries.append(row["id"])
        entered_send.set()
        assert release_send.wait(timeout=5)

    monkeypatch.setattr(notifications, "_deliver_email", blocked_delivery)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(notifications.process_one_notification)
        assert entered_send.wait(timeout=5)
        try:
            assert notifications.process_one_notification() == "empty"
        finally:
            release_send.set()
        assert first.result(timeout=5) == "sent"
    assert len(deliveries) == 1
    assert _outbox(request["id"])[0]["status"] == "sent"


def test_smtp_delivery_uses_standard_library_and_builds_plain_and_html_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_messages = []
    connection_args = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            connection_args.append((host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(notifications.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("CAMPUSOPS_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("CAMPUSOPS_SMTP_PORT", "1025")
    monkeypatch.setenv("CAMPUSOPS_SMTP_TIMEOUT", "3")
    monkeypatch.setenv("CAMPUSOPS_SMTP_USERNAME", "")
    monkeypatch.setenv("CAMPUSOPS_SMTP_PASSWORD", "")
    monkeypatch.setenv("CAMPUSOPS_SMTP_TLS", "false")
    monkeypatch.setenv("CAMPUSOPS_SMTP_SSL", "false")
    notifications._deliver_email({
        "recipient_email": "admin@campusops.example.test",
        "subject": "CampusOps test",
        "text_body": "Plain body",
        "html_body": "<p>HTML body</p>",
    })
    assert connection_args == [("127.0.0.1", 1025, 3)]
    assert len(sent_messages) == 1
    assert sent_messages[0].get_payload()[0].get_content() == "Plain body\n"
    assert sent_messages[0].get_payload()[1].get_content() == "<p>HTML body</p>\n"
