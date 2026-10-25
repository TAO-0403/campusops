from concurrent.futures import ThreadPoolExecutor
import csv
import io
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from app import purchasing
from app.config import get_attachment_storage_dir
from app.db import connect
from app.main import app
from app.seed_demo_requests import SHOWCASE_STATUSES, TITLES, _sample_event_timestamps

APPLICANT_A = "alex.morgan@campusops.test"
APPLICANT_A_PASSWORD = "Northstar-Applicant-2026!"
APPLICANT_B = "jordan.taylor@campusops.test"
APPLICANT_B_PASSWORD = "Riverstone-Applicant-2026!"
ADMIN = "casey.lee@campusops.test"
ADMIN_PASSWORD = "Harbor-Admin-2026!"


def sign_in(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def request_payload(client: TestClient, **overrides: object) -> dict:
    departments = client.get("/api/departments").json()
    science = next(item for item in departments if item["code"] == "SCI")
    return {
        "title": "Laboratory safety supplies",
        "description": "Protective supplies for the spring teaching labs.",
        "vendor": "Example Scientific Supply",
        "department_id": science["id"],
        "amount": "128.40",
        **overrides,
    }


def create_request(client: TestClient, csrf_token: str, **overrides: object) -> dict:
    response = client.post(
        "/api/requests",
        json=request_payload(client, **overrides),
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 201
    return response.json()


def test_health_check_still_checks_postgresql() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["database"]["status"] == "ok"


def test_protected_endpoints_require_login() -> None:
    with TestClient(app) as client:
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/requests").status_code == 401
        assert client.post("/api/requests", json={}).status_code == 401


def test_client_cannot_choose_request_owner_or_status() -> None:
    with TestClient(app) as client:
        csrf = sign_in(client, APPLICANT_A, APPLICANT_A_PASSWORD)
        payload = request_payload(client, requester_id=99999, status="Approved", role="admin")
        response = client.post(
            "/api/requests",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )

    assert response.status_code == 422


def test_requester_cannot_read_or_edit_another_users_request() -> None:
    with TestClient(app) as client_a:
        csrf_a = sign_in(client_a, APPLICANT_A, APPLICANT_A_PASSWORD)
        created = create_request(client_a, csrf_a)

    with TestClient(app) as client_b:
        csrf_b = sign_in(client_b, APPLICANT_B, APPLICANT_B_PASSWORD)
        assert client_b.get("/api/requests").json()["items"] == []
        assert client_b.get(f"/api/requests/{created['id']}").status_code == 404
        update = client_b.put(
            f"/api/requests/{created['id']}",
            json=request_payload(client_b),
            headers={"X-CSRF-Token": csrf_b},
        )
        assert update.status_code == 404


def test_admin_is_read_only_and_cannot_be_granted_requester_actions() -> None:
    with TestClient(app) as applicant_client:
        csrf = sign_in(applicant_client, APPLICANT_A, APPLICANT_A_PASSWORD)
        created = create_request(applicant_client, csrf)

    with TestClient(app) as admin_client:
        admin_csrf = sign_in(admin_client, ADMIN, ADMIN_PASSWORD)
        assert admin_client.get("/api/requests").json()["total"] == 1
        assert admin_client.post(
            "/api/requests",
            json=request_payload(admin_client),
            headers={"X-CSRF-Token": admin_csrf},
        ).status_code == 403
        assert admin_client.put(
            f"/api/requests/{created['id']}",
            json=request_payload(admin_client),
            headers={"X-CSRF-Token": admin_csrf},
        ).status_code == 403
        assert admin_client.post(
            f"/api/requests/{created['id']}/submit",
            headers={"X-CSRF-Token": admin_csrf},
        ).status_code == 403


def test_invalid_amounts_and_missing_submission_fields_are_rejected() -> None:
    with TestClient(app) as client:
        csrf = sign_in(client, APPLICANT_A, APPLICANT_A_PASSWORD)
        assert client.post(
            "/api/requests",
            json=request_payload(client, amount="-0.01"),
            headers={"X-CSRF-Token": csrf},
        ).status_code == 422
        assert client.post(
            "/api/requests",
            json=request_payload(client, amount="1.001"),
            headers={"X-CSRF-Token": csrf},
        ).status_code == 422

        incomplete = create_request(
            client,
            csrf,
            title="",
            description="",
            vendor="",
            department_id=None,
            amount="0.00",
        )
        response = client.post(
            f"/api/requests/{incomplete['id']}/submit",
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 422
        assert "amount greater than zero" in response.json()["detail"]


def test_submission_is_atomic_logged_and_cannot_be_repeated_or_edited() -> None:
    with TestClient(app) as client:
        csrf = sign_in(client, APPLICANT_A, APPLICANT_A_PASSWORD)
        created = create_request(client, csrf)

        submitted = client.post(
            f"/api/requests/{created['id']}/submit",
            headers={"X-CSRF-Token": csrf},
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "Submitted"

        detail = client.get(f"/api/requests/{created['id']}").json()
        submit_events = [event for event in detail["events"] if event["event_type"] == "Submitted"]
        assert len(submit_events) == 1
        assert submit_events[0]["previous_status"] == "Draft"
        assert submit_events[0]["new_status"] == "Submitted"

        assert client.post(
            f"/api/requests/{created['id']}/submit",
            headers={"X-CSRF-Token": csrf},
        ).status_code == 409
        assert client.put(
            f"/api/requests/{created['id']}",
            json=request_payload(client),
            headers={"X-CSRF-Token": csrf},
        ).status_code == 409


def test_request_data_survives_a_new_client_session() -> None:
    with TestClient(app) as first_client:
        csrf = sign_in(first_client, APPLICANT_A, APPLICANT_A_PASSWORD)
        created = create_request(first_client, csrf)

    with TestClient(app) as refreshed_client:
        sign_in(refreshed_client, APPLICANT_A, APPLICANT_A_PASSWORD)
        detail = refreshed_client.get(f"/api/requests/{created['id']}")

    assert detail.status_code == 200
    assert detail.json()["title"] == "Laboratory safety supplies"
    assert detail.json()["amount"] == "128.40"


def test_logout_revokes_the_server_side_session() -> None:
    with TestClient(app) as client:
        csrf = sign_in(client, APPLICANT_A, APPLICANT_A_PASSWORD)
        assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
        assert client.get("/api/auth/me").status_code == 401


def test_mutating_request_requires_csrf_token() -> None:
    with TestClient(app) as client:
        sign_in(client, APPLICANT_A, APPLICANT_A_PASSWORD)
        response = client.post("/api/requests", json=request_payload(client))

    assert response.status_code == 403


def test_complete_return_resubmit_approval_history() -> None:
    with TestClient(app) as applicant:
        applicant_csrf = sign_in(applicant, APPLICANT_A, APPLICANT_A_PASSWORD)
        created = create_request(applicant, applicant_csrf)
        request_id = created["id"]
        assert applicant.post(f"/api/requests/{request_id}/submit", headers={"X-CSRF-Token": applicant_csrf}).json()["status"] == "Submitted"

    with TestClient(app) as admin:
        admin_csrf = sign_in(admin, ADMIN, ADMIN_PASSWORD)
        returned = admin.post(f"/api/requests/{request_id}/return", json={"reason": "Please clarify the teaching-lab use."}, headers={"X-CSRF-Token": admin_csrf})
        assert returned.status_code == 200
        assert returned.json()["status"] == "Returned"

    with TestClient(app) as applicant:
        applicant_csrf = sign_in(applicant, APPLICANT_A, APPLICANT_A_PASSWORD)
        saved = applicant.put(f"/api/requests/{request_id}", json=request_payload(applicant, amount="138.40"), headers={"X-CSRF-Token": applicant_csrf})
        assert saved.status_code == 200
        assert saved.json()["status"] == "Returned"
        assert saved.json()["amount"] == "138.40"
        resubmitted = applicant.post(f"/api/requests/{request_id}/resubmit", json={"comment": "Added the requested teaching details."}, headers={"X-CSRF-Token": applicant_csrf})
        assert resubmitted.status_code == 200
        assert resubmitted.json()["status"] == "Submitted"
        assert applicant.put(f"/api/requests/{request_id}", json=request_payload(applicant), headers={"X-CSRF-Token": applicant_csrf}).status_code == 409

    with TestClient(app) as admin:
        admin_csrf = sign_in(admin, ADMIN, ADMIN_PASSWORD)
        approved = admin.post(f"/api/requests/{request_id}/approve", json={"comment": "Approved for the spring labs."}, headers={"X-CSRF-Token": admin_csrf})
        assert approved.status_code == 200
        assert approved.json()["status"] == "Approved"
        assert admin.post(f"/api/requests/{request_id}/approve", json={}, headers={"X-CSRF-Token": admin_csrf}).status_code == 409

        # A future-dated legacy event must not reorder the persisted transition history.
        with connect() as connection:
            connection.execute(
                "UPDATE request_events SET created_at = now() + interval '1 day' WHERE request_id = %s AND event_type = 'Submitted'",
                (request_id,),
            )
        detail = admin.get(f"/api/requests/{request_id}").json()

    transitions = [(event["previous_status"], event["new_status"]) for event in detail["events"] if event["event_type"] in ("Submitted", "Returned", "Resubmitted", "Approved")]
    assert transitions == [("Draft", "Submitted"), ("Submitted", "Returned"), ("Returned", "Submitted"), ("Submitted", "Approved")]
    decisions = {event["event_type"]: event for event in detail["events"] if event["event_type"] in ("Returned", "Resubmitted", "Approved")}
    assert decisions["Returned"]["actor_name"] == "Casey Lee"
    assert decisions["Returned"]["comment"] == "Please clarify the teaching-lab use."
    assert decisions["Resubmitted"]["actor_name"] == "Alex Morgan"
    assert decisions["Resubmitted"]["comment"] == "Added the requested teaching details."
    assert decisions["Approved"]["comment"] == "Approved for the spring labs."
    assert all(event["created_at"] for event in decisions.values())


def test_showcase_event_timestamps_are_past_and_follow_transitions() -> None:
    now = datetime.now(timezone.utc)
    for index, final_status in enumerate(SHOWCASE_STATUSES):
        created_at, submitted_at, decision_at = _sample_event_timestamps(now, index)
        assert created_at < submitted_at < decision_at < now
        if final_status != "Draft":
            assert created_at < submitted_at
        if final_status in ("Returned", "Approved"):
            assert submitted_at < decision_at
    assert len(TITLES) == len(SHOWCASE_STATUSES)


def test_return_requires_nonblank_reason_and_only_submitted_requests_can_transition() -> None:
    with TestClient(app) as applicant:
        applicant_csrf = sign_in(applicant, APPLICANT_A, APPLICANT_A_PASSWORD)
        draft = create_request(applicant, applicant_csrf)
        assert applicant.post(f"/api/requests/{draft['id']}/resubmit", json={}, headers={"X-CSRF-Token": applicant_csrf}).status_code == 409

    with TestClient(app) as admin:
        admin_csrf = sign_in(admin, ADMIN, ADMIN_PASSWORD)
        url = f"/api/requests/{draft['id']}"
        assert admin.post(f"{url}/approve", json={}, headers={"X-CSRF-Token": admin_csrf}).status_code == 409
        assert admin.post(f"{url}/return", json={"reason": "   "}, headers={"X-CSRF-Token": admin_csrf}).status_code == 422
        assert admin.post(f"{url}/return", json={"reason": "reason"}, headers={"X-CSRF-Token": admin_csrf}).status_code == 409


def test_roles_and_ownership_are_enforced_for_review_and_resubmission() -> None:
    with TestClient(app) as owner:
        owner_csrf = sign_in(owner, APPLICANT_A, APPLICANT_A_PASSWORD)
        created = create_request(owner, owner_csrf)
        request_id = created["id"]
        owner.post(f"/api/requests/{request_id}/submit", headers={"X-CSRF-Token": owner_csrf})

    with TestClient(app) as applicant_b:
        csrf_b = sign_in(applicant_b, APPLICANT_B, APPLICANT_B_PASSWORD)
        assert applicant_b.post(f"/api/requests/{request_id}/approve", json={}, headers={"X-CSRF-Token": csrf_b}).status_code == 403
        assert applicant_b.post(f"/api/requests/{request_id}/return", json={"reason": "No"}, headers={"X-CSRF-Token": csrf_b}).status_code == 403

    with TestClient(app) as admin:
        admin_csrf = sign_in(admin, ADMIN, ADMIN_PASSWORD)
        admin.post(f"/api/requests/{request_id}/return", json={"reason": "Please revise."}, headers={"X-CSRF-Token": admin_csrf})
        assert admin.post(f"/api/requests/{request_id}/resubmit", json={}, headers={"X-CSRF-Token": admin_csrf}).status_code == 403

    with TestClient(app) as applicant_b:
        csrf_b = sign_in(applicant_b, APPLICANT_B, APPLICANT_B_PASSWORD)
        assert applicant_b.get(f"/api/requests/{request_id}").status_code == 404
        assert applicant_b.put(f"/api/requests/{request_id}", json=request_payload(applicant_b), headers={"X-CSRF-Token": csrf_b}).status_code == 404
        assert applicant_b.post(f"/api/requests/{request_id}/resubmit", json={}, headers={"X-CSRF-Token": csrf_b}).status_code == 404


def test_concurrent_approvals_create_only_one_decision() -> None:
    with TestClient(app) as applicant:
        applicant_csrf = sign_in(applicant, APPLICANT_A, APPLICANT_A_PASSWORD)
        request_id = create_request(applicant, applicant_csrf)["id"]
        applicant.post(f"/api/requests/{request_id}/submit", headers={"X-CSRF-Token": applicant_csrf})

    clients = [TestClient(app), TestClient(app)]
    try:
        csrf_tokens = [sign_in(client, ADMIN, ADMIN_PASSWORD) for client in clients]
        def approve(index: int) -> int:
            response = clients[index].post(f"/api/requests/{request_id}/approve", json={"comment": f"Review {index}"}, headers={"X-CSRF-Token": csrf_tokens[index]})
            return response.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, (0, 1)))
        assert sorted(results) == [200, 409]
        detail = clients[0].get(f"/api/requests/{request_id}").json()
        assert detail["status"] == "Approved"
        assert len([event for event in detail["events"] if event["event_type"] == "Approved"]) == 1
    finally:
        for client in clients:
            client.close()


def test_request_search_combined_filters_sorting_and_pagination() -> None:
    with TestClient(app) as client:
        csrf = sign_in(client, APPLICANT_A, APPLICANT_A_PASSWORD)
        departments = client.get("/api/departments").json()
        science = next(row["id"] for row in departments if row["code"] == "SCI")
        library = next(row["id"] for row in departments if row["code"] == "LIB")
        science_rows = []
        for index in range(22):
            department_id = science if index % 2 == 0 else library
            created = create_request(
                client,
                csrf,
                title=f"RequestBatch laboratory item {index:02d}",
                department_id=department_id,
                amount="100.00" if index % 4 else "250.00",
            )
            if department_id == science:
                science_rows.append((created["id"], float(created["amount"])))
            assert client.post(f"/api/requests/{created['id']}/submit", headers={"X-CSRF-Token": csrf}).status_code == 200

        params = {"search": "requestbatch", "status": "Submitted", "department_id": science, "sort_by": "amount", "sort_order": "desc", "page_size": 10}
        first_page = client.get("/api/requests", params={**params, "page": 1})
        second_page = client.get("/api/requests", params={**params, "page": 2})
        assert first_page.status_code == 200, first_page.text
        assert first_page.json()["total"] == 11
        assert first_page.json()["page"] == 1
        assert first_page.json()["page_size"] == 10
        assert len(first_page.json()["items"]) == 10
        assert len(second_page.json()["items"]) == 1
        combined_ids = [row["id"] for row in first_page.json()["items"] + second_page.json()["items"]]
        expected_ids = [request_id for request_id, _ in sorted(science_rows, key=lambda row: (row[1], row[0]), reverse=True)]
        assert combined_ids == expected_ids
        amounts = [float(row["amount"]) for row in first_page.json()["items"]]
        assert amounts == sorted(amounts, reverse=True)
        overview = client.get("/api/requests/overview", params={key: value for key, value in params.items() if key not in ("sort_by", "sort_order", "page_size")}).json()
        assert overview["total_requests"] == 11
        assert overview["pending_review"] == 11
        assert overview["approved_amount"] == "0.00"
        assert overview["requests_by_department"] == [{"department_id": science, "department_name": "Science", "count": 11}]
        assert client.get("/api/requests", params={**params, "page_size": 15}).status_code == 422
        assert client.get("/api/requests", params={**params, "sort_by": "amount;DROP TABLE users"}).status_code == 422


def test_request_overview_aggregates_all_matching_records_and_respects_user_scope() -> None:
    with TestClient(app) as alex:
        alex_csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        departments = alex.get("/api/departments").json()
        science = next(row["id"] for row in departments if row["code"] == "SCI")
        library = next(row["id"] for row in departments if row["code"] == "LIB")
        create_request(alex, alex_csrf, title="Metrics draft", department_id=science, amount="50.00")
        submitted = create_request(alex, alex_csrf, title="Metrics pending", department_id=library, amount="80.00")
        returned = create_request(alex, alex_csrf, title="Metrics returned", department_id=science, amount="120.00")
        approved = create_request(alex, alex_csrf, title="Metrics approved", department_id=library, amount="200.00")
        for request in (submitted, returned, approved):
            assert alex.post(f"/api/requests/{request['id']}/submit", headers={"X-CSRF-Token": alex_csrf}).status_code == 200

    with TestClient(app) as casey:
        casey_csrf = sign_in(casey, ADMIN, ADMIN_PASSWORD)
        assert casey.post(f"/api/requests/{returned['id']}/return", json={"reason": "Please revise."}, headers={"X-CSRF-Token": casey_csrf}).status_code == 200
        assert casey.post(f"/api/requests/{approved['id']}/approve", json={}, headers={"X-CSRF-Token": casey_csrf}).status_code == 200

    with TestClient(app) as jordan:
        jordan_csrf = sign_in(jordan, APPLICANT_B, APPLICANT_B_PASSWORD)
        jordan_request = create_request(jordan, jordan_csrf, title="Private Jordan request", amount="999.99")
        assert jordan.post(f"/api/requests/{jordan_request['id']}/submit", headers={"X-CSRF-Token": jordan_csrf}).status_code == 200
        jordan_overview = jordan.get("/api/requests/overview").json()
        assert jordan_overview["total_requests"] == 1
        assert jordan_overview["pending_review"] == 1
        assert jordan_overview["approved_amount"] == "0.00"

    with TestClient(app) as alex:
        sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        listing = alex.get("/api/requests", params={"page": 1, "page_size": 10}).json()
        overview_page_one = alex.get("/api/requests/overview").json()
        overview_page_two = alex.get("/api/requests/overview", params={"page": 2, "page_size": 10, "sort_by": "amount", "sort_order": "asc"}).json()

    assert listing["total"] == 4
    assert all(row["requester_name"] == "Alex Morgan" for row in listing["items"])
    assert overview_page_one == overview_page_two
    assert overview_page_one["total_requests"] == 4
    assert overview_page_one["pending_review"] == 1
    assert overview_page_one["changes_requested"] == 1
    assert overview_page_one["approved_amount"] == "200.00"
    assert {row["status"]: row["count"] for row in overview_page_one["requests_by_status"]} == {
        "Draft": 1, "Submitted": 1, "Returned": 1, "Approved": 1,
    }
    assert {row["department_name"]: row["count"] for row in overview_page_one["requests_by_department"]} == {
        "Science": 2, "Library": 2,
    }


def _parse_csv_export(response) -> list[dict[str, str]]:
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))


def test_csv_export_requires_admin_and_returns_download() -> None:
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/requests/export.csv").status_code == 401

    with TestClient(app) as applicant:
        sign_in(applicant, APPLICANT_A, APPLICANT_A_PASSWORD)
        assert applicant.get("/api/requests/export.csv").status_code == 403

    with TestClient(app) as admin:
        sign_in(admin, ADMIN, ADMIN_PASSWORD)
        response = admin.get("/api/requests/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="campusops-requests-' in response.headers["content-disposition"]
    reader = csv.reader(io.StringIO(response.content.decode("utf-8-sig"), newline=""))
    assert next(reader) == [
        "Request ID", "Title", "Applicant", "Department", "Vendor",
        "Amount (USD)", "Status", "Created At", "Updated At",
    ]
    assert list(reader) == []


def test_csv_export_applies_filters_sorting_and_ignores_page_limits() -> None:
    with TestClient(app) as applicant:
        csrf = sign_in(applicant, APPLICANT_A, APPLICANT_A_PASSWORD)
        departments = applicant.get("/api/departments").json()
        science = next(row["id"] for row in departments if row["code"] == "SCI")
        library = next(row["id"] for row in departments if row["code"] == "LIB")
        expected = []
        for index in range(12):
            amount = Decimal(10 + index % 4)
            created = create_request(
                applicant,
                csrf,
                title=f"CSV export batch {index:02d}",
                department_id=science,
                amount=f"{amount:.2f}",
            )
            assert applicant.post(
                f"/api/requests/{created['id']}/submit",
                headers={"X-CSRF-Token": csrf},
            ).status_code == 200
            expected.append((amount, created["id"]))

        create_request(applicant, csrf, title="CSV export batch draft", department_id=science)
        other_department = create_request(applicant, csrf, title="CSV export batch other department", department_id=library)
        applicant.post(
            f"/api/requests/{other_department['id']}/submit",
            headers={"X-CSRF-Token": csrf},
        )
        unrelated = create_request(applicant, csrf, title="Unrelated submitted request", department_id=science)
        applicant.post(f"/api/requests/{unrelated['id']}/submit", headers={"X-CSRF-Token": csrf})

    with TestClient(app) as admin:
        sign_in(admin, ADMIN, ADMIN_PASSWORD)
        response = admin.get(
            "/api/requests/export.csv",
            params={
                "search": "CSV export batch",
                "status": "Submitted",
                "department_id": science,
                "sort_by": "amount",
                "sort_order": "asc",
                "page": 2,
                "page_size": 10,
            },
        )

    assert response.status_code == 200
    rows = _parse_csv_export(response)
    expected.sort(key=lambda item: (item[0], item[1]))
    assert [int(row["Request ID"]) for row in rows] == [request_id for _, request_id in expected]
    assert [row["Amount (USD)"] for row in rows] == [f"{amount:.2f}" for amount, _ in expected]
    assert len(rows) == 12


def test_csv_export_empty_result_special_characters_and_formula_safety() -> None:
    with TestClient(app) as applicant:
        csrf = sign_in(applicant, APPLICANT_A, APPLICANT_A_PASSWORD)
        department = next(row for row in applicant.get("/api/departments").json() if row["code"] == "SCI")
        with connect() as connection:
            original_name = connection.execute(
                "SELECT full_name FROM users WHERE email = %s", (APPLICANT_A,)
            ).fetchone()["full_name"]
            original_department = connection.execute(
                "SELECT name FROM departments WHERE id = %s", (department["id"],)
            ).fetchone()["name"]
            connection.execute("UPDATE users SET full_name = %s WHERE email = %s", (" \t@Applicant!A1", APPLICANT_A))
            connection.execute("UPDATE departments SET name = %s WHERE id = %s", ("\t-Science", department["id"]))

        special_title = 'Quoted, "request"\nsecond line'
        special_vendor = 'Vendor, "quoted"\nSupply'
        created = create_request(
            applicant,
            csrf,
            title=special_title,
            vendor=special_vendor,
            amount="57.5",
        )
        formula_request = create_request(applicant, csrf, title="Formula safety request", amount="1.00")
        with connect() as connection:
            connection.execute(
                "UPDATE purchase_requests SET title = %s, vendor = %s WHERE id = %s",
                (" \t=1+1", " +SUM(1,1)", formula_request["id"]),
            )

        try:
            with TestClient(app) as admin:
                sign_in(admin, ADMIN, ADMIN_PASSWORD)
                response = admin.get("/api/requests/export.csv", params={"search": "Quoted"})
                formula_response = admin.get("/api/requests/export.csv")
                empty_response = admin.get("/api/requests/export.csv", params={"search": "does not exist"})
        finally:
            with connect() as connection:
                connection.execute("UPDATE users SET full_name = %s WHERE email = %s", (original_name, APPLICANT_A))
                connection.execute("UPDATE departments SET name = %s WHERE id = %s", (original_department, department["id"]))

        detail = applicant.get(f"/api/requests/{created['id']}").json()

    assert response.status_code == 200
    rows = _parse_csv_export(response)
    assert len(rows) == 1
    row = rows[0]
    assert row["Title"] == special_title
    assert row["Vendor"] == special_vendor
    assert row["Applicant"] == "' \t@Applicant!A1"
    assert row["Department"] == "'\t-Science"
    assert row["Amount (USD)"] == "57.50"
    assert datetime.fromisoformat(row["Created At"]).utcoffset() is not None
    assert datetime.fromisoformat(row["Updated At"]).utcoffset() is not None
    assert row["Title"] == detail["title"] and row["Vendor"] == detail["vendor"]
    formula_row = next(item for item in _parse_csv_export(formula_response) if int(item["Request ID"]) == formula_request["id"])
    assert formula_row["Title"] == "' \t=1+1"
    assert formula_row["Vendor"] == "' +SUM(1,1)"
    assert formula_row["Applicant"] == "' \t@Applicant!A1"
    assert formula_row["Department"] == "'\t-Science"
    assert empty_response.status_code == 200
    empty_reader = csv.reader(io.StringIO(empty_response.content.decode("utf-8-sig"), newline=""))
    assert next(empty_reader) == [
        "Request ID", "Title", "Applicant", "Department", "Vendor",
        "Amount (USD)", "Status", "Created At", "Updated At",
    ]
    assert list(empty_reader) == []


def _minimal_pdf(marker: bytes = b"") -> bytes:
    chunks = [b"%PDF-1.4\n", marker]
    object_bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [] /Count 0 >>",
    ]
    offsets = [0]
    for index, body in enumerate(object_bodies, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(b"xref\n0 3\n0000000000 65535 f \n")
    chunks.extend(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    chunks.append(
        b"trailer\n<< /Size 3 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return b"".join(chunks)


def _minimal_pdf_with_size(target_size: int) -> bytes:
    marker = b""
    for _ in range(5):
        content = _minimal_pdf(marker)
        difference = target_size - len(content)
        if difference == 0:
            return content
        marker = b"%" + b"x" * max(0, len(marker) + difference - 2) + b"\n"
    raise AssertionError("Could not create a PDF at the requested byte size.")


def _upload_attachment(
    client: TestClient,
    request_id: int,
    filename: str,
    content: bytes | None = None,
    csrf_token: str | None = None,
    content_type: str = "application/pdf",
):
    headers = {"X-CSRF-Token": csrf_token} if csrf_token is not None else {}
    body = _minimal_pdf() if content is None else content
    return client.post(
        f"/api/requests/{request_id}/attachment",
        files={"file": (filename, body, content_type)},
        headers=headers,
    )


def _create_draft_for(client: TestClient, csrf: str, **overrides: object) -> dict:
    return create_request(client, csrf, **overrides)


def test_quotation_attachment_upload_view_download_delete_and_history() -> None:
    pdf = _minimal_pdf()
    filename = "Vendor quote 报价 2026.pdf"
    with TestClient(app) as alex:
        csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        request = _create_draft_for(alex, csrf, title="Quotation lifecycle")
        assert alex.get(f"/api/requests/{request['id']}").json()["attachment"] is None

        uploaded = _upload_attachment(alex, request["id"], filename, pdf, csrf, content_type="text/plain")
        assert uploaded.status_code == 200
        assert uploaded.json()["original_filename"] == filename
        assert uploaded.json()["file_size"] == len(pdf)
        assert set(uploaded.json()) == {"original_filename", "file_size", "uploaded_at"}

        detail = alex.get(f"/api/requests/{request['id']}").json()
        assert detail["attachment"]["original_filename"] == filename
        assert detail["attachment"]["file_size"] == len(pdf)
        viewed = alex.get(f"/api/requests/{request['id']}/attachment")
        downloaded = alex.get(f"/api/requests/{request['id']}/attachment?download=true")
        assert viewed.status_code == downloaded.status_code == 200
        assert viewed.content == downloaded.content == pdf
        assert viewed.headers["content-type"] == "application/pdf"
        assert viewed.headers["cache-control"] == "private, no-store"
        assert viewed.headers["content-disposition"].startswith("inline;")
        assert "filename*=UTF-8''Vendor%20quote%20%E6%8A%A5%E4%BB%B7%202026.pdf" in downloaded.headers["content-disposition"]
        assert downloaded.headers["content-disposition"].startswith("attachment;")

        deleted = alex.delete(f"/api/requests/{request['id']}/attachment", headers={"X-CSRF-Token": csrf})
        assert deleted.status_code == 200
        assert alex.get(f"/api/requests/{request['id']}/attachment").status_code == 404
        final_detail = alex.get(f"/api/requests/{request['id']}").json()
        assert final_detail["attachment"] is None
        assert [event["event_type"] for event in final_detail["events"] if event["event_type"].startswith("Attachment")] == [
            "AttachmentUploaded", "AttachmentDeleted",
        ]
        attachment_events = [event for event in final_detail["events"] if event["event_type"].startswith("Attachment")]
        assert all(event["actor_name"] == "Alex Morgan" and event["created_at"] for event in attachment_events)
        assert [event["details"]["filename"] for event in attachment_events] == [filename, filename]
        assert not list(get_attachment_storage_dir().glob("*.pdf"))


def test_quotation_attachment_replacement_updates_metadata_and_removes_old_file() -> None:
    first_pdf = _minimal_pdf()
    second_pdf = _minimal_pdf(b"% replacement\n")
    with TestClient(app) as alex:
        csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        request = _create_draft_for(alex, csrf, title="Quotation replacement")
        assert _upload_attachment(alex, request["id"], "First quote.pdf", first_pdf, csrf).status_code == 200
        with connect() as connection:
            old_storage_id = connection.execute(
                "SELECT storage_id FROM request_attachments WHERE request_id = %s", (request["id"],)
            ).fetchone()["storage_id"]

        replaced = _upload_attachment(alex, request["id"], "Updated quote.pdf", second_pdf, csrf)
        assert replaced.status_code == 200
        assert replaced.json()["original_filename"] == "Updated quote.pdf"
        assert replaced.json()["file_size"] == len(second_pdf)
        with connect() as connection:
            attachments = connection.execute(
                "SELECT storage_id, original_filename, file_size FROM request_attachments WHERE request_id = %s",
                (request["id"],),
            ).fetchall()
            events = connection.execute(
                "SELECT event_type FROM request_events WHERE request_id = %s AND event_type LIKE %s ORDER BY id",
                (request["id"], "Attachment%"),
            ).fetchall()

        assert len(attachments) == 1
        assert attachments[0]["storage_id"] != old_storage_id
        assert attachments[0]["original_filename"] == "Updated quote.pdf"
        assert attachments[0]["file_size"] == len(second_pdf)
        assert [event["event_type"] for event in events] == ["AttachmentUploaded", "AttachmentReplaced"]
        assert not (get_attachment_storage_dir() / f"{old_storage_id}.pdf").exists()
        assert alex.get(f"/api/requests/{request['id']}/attachment").content == second_pdf
        assert len(list(get_attachment_storage_dir().glob("*.pdf"))) == 1


def test_quotation_attachment_read_write_permissions_and_csrf() -> None:
    pdf = _minimal_pdf()
    with TestClient(app) as alex:
        alex_csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        request = _create_draft_for(alex, alex_csrf, title="Private quotation")
        assert _upload_attachment(alex, request["id"], "Private.pdf", pdf, alex_csrf).status_code == 200

        assert _upload_attachment(alex, request["id"], "No csrf.pdf", pdf).status_code == 403
        assert alex.delete(f"/api/requests/{request['id']}/attachment").status_code == 403

    with TestClient(app) as anonymous:
        assert anonymous.get(f"/api/requests/{request['id']}/attachment").status_code == 401
        assert anonymous.get(f"/api/requests/{request['id']}/attachment?download=true").status_code == 401

    with TestClient(app) as jordan:
        jordan_csrf = sign_in(jordan, APPLICANT_B, APPLICANT_B_PASSWORD)
        assert jordan.get(f"/api/requests/{request['id']}/attachment").status_code == 404
        assert _upload_attachment(jordan, request["id"], "Other.pdf", pdf, jordan_csrf).status_code == 404
        assert jordan.delete(f"/api/requests/{request['id']}/attachment", headers={"X-CSRF-Token": jordan_csrf}).status_code == 404

    with TestClient(app) as admin:
        admin_csrf = sign_in(admin, ADMIN, ADMIN_PASSWORD)
        assert admin.get(f"/api/requests/{request['id']}/attachment").content == pdf
        assert admin.get(f"/api/requests/{request['id']}/attachment?download=true").headers["content-disposition"].startswith("attachment;")
        assert _upload_attachment(admin, request["id"], "Admin.pdf", pdf, admin_csrf).status_code == 403
        assert admin.delete(f"/api/requests/{request['id']}/attachment", headers={"X-CSRF-Token": admin_csrf}).status_code == 403

    with TestClient(app) as alex:
        sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        assert alex.get(f"/api/requests/{request['id']}/attachment").content == pdf


def test_quotation_attachment_cannot_change_after_submission_or_approval() -> None:
    pdf = _minimal_pdf()
    with TestClient(app) as alex:
        csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        request = create_request(
            alex,
            csrf,
            title="Locked quotation",
            description="Request details for review.",
            vendor="Example vendor",
            amount="25.00",
        )
        assert _upload_attachment(alex, request["id"], "Original.pdf", pdf, csrf).status_code == 200
        assert alex.post(f"/api/requests/{request['id']}/submit", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert _upload_attachment(alex, request["id"], "Changed.pdf", pdf, csrf).status_code == 409
        assert alex.delete(f"/api/requests/{request['id']}/attachment", headers={"X-CSRF-Token": csrf}).status_code == 409

    with TestClient(app) as admin:
        admin_csrf = sign_in(admin, ADMIN, ADMIN_PASSWORD)
        assert admin.post(f"/api/requests/{request['id']}/approve", json={}, headers={"X-CSRF-Token": admin_csrf}).status_code == 200

    with TestClient(app) as alex:
        csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        assert _upload_attachment(alex, request["id"], "Changed after approval.pdf", pdf, csrf).status_code == 409
        assert alex.delete(f"/api/requests/{request['id']}/attachment", headers={"X-CSRF-Token": csrf}).status_code == 409
        assert alex.get(f"/api/requests/{request['id']}/attachment").content == pdf


def test_quotation_attachment_can_be_changed_after_return() -> None:
    pdf = _minimal_pdf()
    revised_pdf = _minimal_pdf(b"% revised quote\n")
    with TestClient(app) as alex:
        csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        request = create_request(
            alex,
            csrf,
            title="Returned quotation",
            description="Details for review.",
            vendor="Example vendor",
            amount="25.00",
        )
        assert _upload_attachment(alex, request["id"], "Original.pdf", pdf, csrf).status_code == 200
        assert alex.post(f"/api/requests/{request['id']}/submit", headers={"X-CSRF-Token": csrf}).status_code == 200

    with TestClient(app) as admin:
        csrf = sign_in(admin, ADMIN, ADMIN_PASSWORD)
        returned = admin.post(
            f"/api/requests/{request['id']}/return",
            json={"reason": "Please provide an updated quotation."},
            headers={"X-CSRF-Token": csrf},
        )
        assert returned.status_code == 200

    with TestClient(app) as alex:
        csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        replaced = _upload_attachment(alex, request["id"], "Revised.pdf", revised_pdf, csrf)
        assert replaced.status_code == 200
        assert replaced.json()["original_filename"] == "Revised.pdf"
        assert alex.get(f"/api/requests/{request['id']}/attachment").content == revised_pdf
        assert alex.delete(f"/api/requests/{request['id']}/attachment", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_quotation_attachment_rejects_invalid_and_oversized_files() -> None:
    with TestClient(app) as alex:
        csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        request = _create_draft_for(alex, csrf, title="File validation")
        max_size_pdf = _minimal_pdf_with_size(5 * 1024 * 1024)
        assert len(max_size_pdf) == 5 * 1024 * 1024
        max_upload = _upload_attachment(alex, request["id"], "maximum-size.pdf", max_size_pdf, csrf)
        assert max_upload.status_code == 200
        assert max_upload.json()["file_size"] == 5 * 1024 * 1024
        assert alex.delete(f"/api/requests/{request['id']}/attachment", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert _upload_attachment(alex, request["id"], "empty.pdf", b"", csrf).status_code == 422
        assert _upload_attachment(alex, request["id"], "text.pdf", b"plain text, not a PDF", csrf).status_code == 422
        assert _upload_attachment(alex, request["id"], "disguised.pdf", b"%PDF-1.4\nnot a PDF structure\n%%EOF\n", csrf).status_code == 422
        assert _upload_attachment(alex, request["id"], "not-a-pdf.txt", _minimal_pdf(), csrf).status_code == 415
        assert _upload_attachment(alex, request["id"], "too-large.pdf", b"%PDF-1.4\n" + b"x" * (5 * 1024 * 1024), csrf).status_code == 413
        assert alex.get(f"/api/requests/{request['id']}").json()["attachment"] is None
        assert not get_attachment_storage_dir().exists() or not list(get_attachment_storage_dir().iterdir())
    assert purchasing._validate_attachment_filename(r"C:\private folder\报价 2026.pdf") == "报价 2026.pdf"


def test_quotation_attachment_failures_clean_files_and_preserve_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _minimal_pdf()

    def fail_event(*args, **kwargs):
        raise RuntimeError("database write failed")

    def fail_storage(*args, **kwargs):
        raise OSError("disk write failed")

    with TestClient(app) as alex:
        csrf = sign_in(alex, APPLICANT_A, APPLICANT_A_PASSWORD)
        request = _create_draft_for(alex, csrf, title="Attachment failure handling")
        with monkeypatch.context() as patcher:
            patcher.setattr(
                purchasing.tempfile,
                "NamedTemporaryFile",
                fail_storage,
            )
            with TestClient(app, raise_server_exceptions=False) as failure_client:
                failure_csrf = sign_in(failure_client, APPLICANT_A, APPLICANT_A_PASSWORD)
                failed_storage = _upload_attachment(failure_client, request["id"], "Disk failure.pdf", pdf, failure_csrf)
        assert failed_storage.status_code == 500
        assert alex.get(f"/api/requests/{request['id']}").json()["attachment"] is None
        assert not get_attachment_storage_dir().exists() or not list(get_attachment_storage_dir().iterdir())

        with monkeypatch.context() as patcher:
            patcher.setattr(purchasing, "_record_attachment_event", fail_event)
            with TestClient(app, raise_server_exceptions=False) as failure_client:
                failure_csrf = sign_in(failure_client, APPLICANT_A, APPLICANT_A_PASSWORD)
                failed_upload = _upload_attachment(failure_client, request["id"], "Never saved.pdf", pdf, failure_csrf)
        assert failed_upload.status_code == 500
        assert alex.get(f"/api/requests/{request['id']}").json()["attachment"] is None
        assert not get_attachment_storage_dir().exists() or not list(get_attachment_storage_dir().iterdir())

        uploaded = _upload_attachment(alex, request["id"], "Keep this.pdf", pdf, csrf)
        assert uploaded.status_code == 200
        with connect() as connection:
            old_attachment = connection.execute(
                "SELECT storage_id, original_filename FROM request_attachments WHERE request_id = %s",
                (request["id"],),
            ).fetchone()

        with monkeypatch.context() as patcher:
            patcher.setattr(purchasing, "_record_attachment_event", fail_event)
            with TestClient(app, raise_server_exceptions=False) as failure_client:
                failure_csrf = sign_in(failure_client, APPLICANT_A, APPLICANT_A_PASSWORD)
                failed_replacement = _upload_attachment(
                    failure_client,
                    request["id"],
                    "Must not replace.pdf",
                    _minimal_pdf(b"% next version\n"),
                    failure_csrf,
                )
        assert failed_replacement.status_code == 500
        with connect() as connection:
            current_attachment = connection.execute(
                "SELECT storage_id, original_filename FROM request_attachments WHERE request_id = %s",
                (request["id"],),
            ).fetchone()
        assert current_attachment == old_attachment
        assert (get_attachment_storage_dir() / f"{old_attachment['storage_id']}.pdf").read_bytes() == pdf
        assert len(list(get_attachment_storage_dir().glob("*.pdf"))) == 1
