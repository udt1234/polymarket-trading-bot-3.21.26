import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from api.dependencies import get_supabase

log = logging.getLogger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
async def login(req: LoginRequest):
    sb = get_supabase()
    try:
        res = sb.auth.sign_in_with_password({"email": req.email, "password": req.password})
        return {
            "access_token": res.session.access_token,
            "refresh_token": res.session.refresh_token,
            "user_id": res.user.id,
        }
    except Exception as e:
        log.error(f"Login failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/logout")
async def logout():
    sb = get_supabase()
    sb.auth.sign_out()
    return {"ok": True}


@router.post("/refresh")
async def refresh(refresh_token: str):
    sb = get_supabase()
    try:
        res = sb.auth.refresh_session(refresh_token)
        return {
            "access_token": res.session.access_token,
            "refresh_token": res.session.refresh_token,
            "user_id": res.user.id,
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
