from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app

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
        assert client_b.get("/api/requests").json() == []
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
        assert len(admin_client.get("/api/requests").json()) == 1
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
