from __future__ import annotations

from email.message import EmailMessage
from html import escape
import smtplib
import ssl
from typing import Any
from urllib.parse import quote

from psycopg import Connection

from app.config import get_frontend_base_url, get_smtp_settings

NOTIFICATION_ACTIONS = {
    "Submitted": "Request submitted for review",
    "Resubmitted": "Request resubmitted for review",
    "Returned": "Request returned for changes",
    "Approved": "Request approved",
}


def _render_notification(request: dict[str, Any], action: str, comment: str | None) -> tuple[str, str, str]:
    action_label = NOTIFICATION_ACTIONS[action]
    request_id = int(request["id"])
    title = str(request["title"] or "Untitled request")
    applicant = str(request["requester_name"])
    department = str(request["department_name"] or "Not specified")
    amount = f"${request['amount']:.2f} USD"
    details_url = f"{get_frontend_base_url()}/requests/{request_id}"
    subject = f"CampusOps: {action_label} — Request #{request_id}"

    text_lines = [
        f"{action_label}.",
        "",
        f"Request #{request_id}: {title}",
        f"Applicant: {applicant}",
        f"Department: {department}",
        f"Amount: {amount}",
    ]
    if action == "Returned":
        text_lines.extend((f"Return reason: {comment or 'No reason provided.'}",))
    elif action == "Approved" and comment:
        text_lines.extend((f"Approval comment: {comment}",))
    text_lines.extend(("", f"Open the request in CampusOps: {details_url}", "Sign in to CampusOps to view the request and any quotation attachment."))

    html_rows = "".join(
        f"<tr><th align=\"left\">{escape(label)}</th><td>{escape(value)}</td></tr>"
        for label, value in (
            ("Request", f"#{request_id}: {title}"),
            ("Applicant", applicant),
            ("Department", department),
            ("Amount", amount),
        )
    )
    outcome_html = ""
    if action == "Returned":
        outcome_html = f"<p><strong>Return reason:</strong> {escape(comment or 'No reason provided.').replace(chr(10), '<br>')}</p>"
    elif action == "Approved" and comment:
        outcome_html = f"<p><strong>Approval comment:</strong> {escape(comment).replace(chr(10), '<br>')}</p>"
    safe_url = escape(details_url, quote=True)
    html_body = (
        "<!doctype html><html><body>"
        f"<h1>{escape(action_label)}</h1><table>{html_rows}</table>{outcome_html}"
        f"<p><a href=\"{safe_url}\">Open request #{request_id} in CampusOps</a></p>"
        "<p>Sign in to CampusOps to view the request and any quotation attachment.</p>"
        "</body></html>"
    )
    return subject, "\n".join(text_lines), html_body


def enqueue_request_notification(
    connection: Connection,
    event_id: int,
    request: dict[str, Any],
    action: str,
    comment: str | None,
) -> int:
    """Store a notification snapshot in the caller's business transaction."""
    from app.config import email_notifications_enabled

    if not email_notifications_enabled() or action not in NOTIFICATION_ACTIONS:
        return 0

    if action in ("Submitted", "Resubmitted"):
        recipients = connection.execute(
            "SELECT id, email FROM users WHERE role = 'admin' AND active ORDER BY id"
        ).fetchall()
    else:
        recipients = connection.execute(
            "SELECT id, email FROM users WHERE id = %s AND active",
            (request["requester_id"],),
        ).fetchall()

    subject, text_body, html_body = _render_notification(request, action, comment)
    inserted = 0
    for recipient in recipients:
        result = connection.execute(
            """
            INSERT INTO email_outbox
                (request_event_id, recipient_user_id, recipient_email, subject, text_body, html_body)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (request_event_id, recipient_user_id) DO NOTHING
            RETURNING id
            """,
            (event_id, recipient["id"], recipient["email"], subject, text_body, html_body),
        ).fetchone()
        inserted += result is not None
    return inserted


def _deliver_email(row: dict[str, Any]) -> None:
    settings = get_smtp_settings()
    if settings["use_tls"] and settings["use_ssl"]:
        raise ValueError("SMTP TLS and SSL cannot both be enabled.")
    username, password = str(settings["username"]), str(settings["password"])
    if bool(username) != bool(password):
        raise ValueError("SMTP username and password must both be configured.")

    message = EmailMessage()
    message["From"] = str(settings["sender"])
    message["To"] = row["recipient_email"]
    message["Subject"] = row["subject"]
    message.set_content(row["text_body"])
    message.add_alternative(row["html_body"], subtype="html")

    timeout = int(settings["timeout"])
    if settings["use_ssl"]:
        with smtplib.SMTP_SSL(
            str(settings["host"]), int(settings["port"]), timeout=timeout, context=ssl.create_default_context()
        ) as smtp:
            if username:
                smtp.login(username, password)
            refused = smtp.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
    else:
        with smtplib.SMTP(str(settings["host"]), int(settings["port"]), timeout=timeout) as smtp:
            if settings["use_tls"]:
                smtp.starttls(context=ssl.create_default_context())
            if username:
                smtp.login(username, password)
            refused = smtp.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)


def _safe_error(error: Exception) -> str:
    return f"SMTP delivery failed ({type(error).__name__})."[:250]


def process_one_notification(retry_seconds: int = 30) -> str:
    """Claim and deliver one notification; return sent, failed, or empty."""
    import uuid

    from app.config import email_notifications_enabled
    from app.db import connect

    if not email_notifications_enabled():
        return "disabled"

    settings = get_smtp_settings()
    token = uuid.uuid4()
    lease_seconds = max(30, int(settings["timeout"]) + 20)
    with connect() as connection:
        row = connection.execute(
            """
            WITH candidate AS (
                SELECT id FROM email_outbox
                WHERE (status = 'pending' AND next_attempt_at <= now())
                   OR (status = 'sending' AND locked_until <= now())
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE email_outbox AS outbox
            SET status = 'sending', claim_token = %s,
                locked_until = now() + make_interval(secs => %s),
                attempt_count = attempt_count + 1
            FROM candidate
            WHERE outbox.id = candidate.id
            RETURNING outbox.*
            """,
            (token, lease_seconds),
        ).fetchone()
    if row is None:
        return "empty"

    try:
        _deliver_email(row)
    except Exception as error:
        with connect() as connection:
            connection.execute(
                """
                UPDATE email_outbox
                SET status = 'pending', claim_token = NULL, locked_until = NULL,
                    next_attempt_at = now() + make_interval(secs => %s), last_error = %s
                WHERE id = %s AND claim_token = %s
                """,
                (max(1, retry_seconds), _safe_error(error), row["id"], token),
            )
        return "failed"

    with connect() as connection:
        connection.execute(
            """
            UPDATE email_outbox
            SET status = 'sent', claim_token = NULL, locked_until = NULL,
                sent_at = now(), last_error = NULL
            WHERE id = %s AND claim_token = %s
            """,
            (row["id"], token),
        )
    return "sent"
