"""Authentication utilities."""
import bcrypt
from itsdangerous import URLSafeTimedSerializer
from fastapi import Request, Response, HTTPException, Depends
from config import SECRET_KEY, SESSION_COOKIE_NAME, SESSION_MAX_AGE, ADMIN_PASSWORD_HASH

serializer = URLSafeTimedSerializer(SECRET_KEY)


def hash_password(password: str) -> str:
    """Hash a password for storing."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    if not hashed:
        return False
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_session(response: Response, user_id: str = "admin"):
    """Create a session cookie."""
    token = serializer.dumps({"user_id": user_id})
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax"
    )


def clear_session(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(SESSION_COOKIE_NAME)


def get_current_user(request: Request) -> str:
    """Get current user from session cookie."""
    # Dev/fallback mode: if no admin password is configured, bypass auth.
    if not ADMIN_PASSWORD_HASH:
        return "admin"

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("user_id")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid session")


def authenticate_user(password: str) -> bool:
    """Authenticate user with password."""
    if not ADMIN_PASSWORD_HASH:
        # No password set, allow any (for first setup)
        return True
    return verify_password(password, ADMIN_PASSWORD_HASH)