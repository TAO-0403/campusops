from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.db import connect
from app.dependencies import AuthContext, SESSION_COOKIE, get_auth_context, require_csrf
from app.schemas import AuthOutput, LoginInput
from app.security import (
    hash_password,
    new_csrf_token,
    new_session_token,
    token_digest,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
SESSION_LIFETIME = timedelta(hours=12)
COOKIE_SECURE = False
_DUMMY_PASSWORD_HASH = hash_password("invalid-demo-password")


@router.post("/login", response_model=AuthOutput)
def login(payload: LoginInput, response: Response) -> dict:
    email = payload.email.strip().lower()
    with connect() as connection:
        user = connection.execute(
            """
            SELECT u.id, u.email, u.full_name, u.role, u.department_id,
                   d.name AS department_name, u.password_hash
            FROM users AS u
            LEFT JOIN departments AS d ON d.id = u.department_id
            WHERE lower(u.email) = %s AND u.active = TRUE
            """,
            (email,),
        ).fetchone()

        encoded_password = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
        password_valid = verify_password(payload.password, encoded_password)
        if not user or not password_valid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

        session_token = new_session_token()
        csrf_token = new_csrf_token()
        connection.execute(
            """
            INSERT INTO auth_sessions (user_id, token_hash, csrf_token, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (
                user["id"],
                token_digest(session_token),
                csrf_token,
                datetime.now(timezone.utc) + SESSION_LIFETIME,
            ),
        )

    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    user.pop("password_hash", None)
    return {"user": user, "csrf_token": csrf_token}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    context: AuthContext = Depends(require_csrf),
) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE auth_sessions SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
            (context.session_id,),
        )
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )


@router.get("/me", response_model=AuthOutput)
def current_user(context: AuthContext = Depends(get_auth_context)) -> dict:
    return {"user": context.user, "csrf_token": context.csrf_token}
