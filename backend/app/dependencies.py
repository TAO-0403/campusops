from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from app.db import connect
from app.security import token_digest, tokens_match

SESSION_COOKIE = "campusops_session"


@dataclass(frozen=True)
class AuthContext:
    user: dict
    session_id: int
    csrf_token: str


def get_auth_context(request: Request) -> AuthContext:
    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")

    with connect() as connection:
        row = connection.execute(
            """
            SELECT s.id AS session_id, s.csrf_token,
                   u.id, u.email, u.full_name, u.role, u.department_id,
                   d.name AS department_name
            FROM auth_sessions AS s
            JOIN users AS u ON u.id = s.user_id
            LEFT JOIN departments AS d ON d.id = u.department_id
            WHERE s.token_hash = %s
              AND s.expires_at > now()
              AND s.revoked_at IS NULL
              AND u.active = TRUE
            """,
            (token_digest(session_token),),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Sign in again.")

    csrf_token = row.pop("csrf_token")
    session_id = row.pop("session_id")
    return AuthContext(user=row, session_id=session_id, csrf_token=csrf_token)


def require_csrf(
    request: Request,
    context: AuthContext = Depends(get_auth_context),
) -> AuthContext:
    supplied = request.headers.get("X-CSRF-Token")
    if not tokens_match(context.csrf_token, supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The request security token is missing or invalid.")
    return context


def require_requester_with_csrf(context: AuthContext = Depends(require_csrf)) -> AuthContext:
    if context.user["role"] != "requester":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only requesters can change purchase requests.")
    return context


def require_admin_with_csrf(context: AuthContext = Depends(require_csrf)) -> AuthContext:
    if context.user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only administrators can review purchase requests.")
    return context
