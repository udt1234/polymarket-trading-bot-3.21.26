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
