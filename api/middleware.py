import time
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from api.config import get_settings
from api.dependencies import get_supabase

_bearer = HTTPBearer(auto_error=False)

_token_cache: dict[str, tuple[str, float]] = {}
TOKEN_CACHE_TTL = 300  # 5 minutes


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = credentials.credentials
    now = time.time()

    if token in _token_cache:
        user_id, cached_at = _token_cache[token]
        if now - cached_at < TOKEN_CACHE_TTL:
            request.state.user_id = user_id
            return user_id

    try:
        sb = get_supabase()
        user_response = sb.auth.get_user(token)
        if not user_response or not user_response.user:
            _token_cache.pop(token, None)
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = user_response.user.id
        _token_cache[token] = (user_id, now)
        request.state.user_id = user_id
        return user_id
    except HTTPException:
        raise
    except Exception:
        _token_cache.pop(token, None)
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def validate_ws_token(token: str | None) -> str | None:
    """Synchronous token validation for WebSocket connections.

    Returns user_id on success, None on failure. The caller is expected to
    close the WebSocket with code 1008 if this returns None. Cache shared with
    require_auth so HTTP and WS share the same TTL.
    """
    if not token:
        return None
    now = time.time()
    if token in _token_cache:
        user_id, cached_at = _token_cache[token]
        if now - cached_at < TOKEN_CACHE_TTL:
            return user_id
    try:
        sb = get_supabase()
        user_response = sb.auth.get_user(token)
        if not user_response or not user_response.user:
            _token_cache.pop(token, None)
            return None
        user_id = user_response.user.id
        _token_cache[token] = (user_id, now)
        return user_id
    except Exception:
        _token_cache.pop(token, None)
        return None
