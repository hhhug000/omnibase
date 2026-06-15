from fastapi import APIRouter, Depends, Header, HTTPException

from src.auth import crypto, store
from src.auth.dependencies import require_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(payload: dict):
    username = payload.get("username")
    email = payload.get("email")
    password = payload.get("password")
    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="username, email, and password are required.")
    try:
        username = crypto.validate_username(username)
        email = crypto.validate_email(email)
        password = crypto.validate_password(password)
        user = await store.create_user(username, email, password)
        return {"status": "success", "user": user}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login")
async def login(payload: dict):
    login_id = payload.get("login")
    password = payload.get("password")
    if not login_id or not password:
        raise HTTPException(status_code=400, detail="login and password are required.")
    try:
        user = await store.get_user_by_login(login_id)
        if not user or not crypto.verify_password(password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid login or password.")
        code_payload = await store.issue_login_code(user["id"])
        return {"status": "success", **code_payload}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/exchange")
async def exchange(payload: dict):
    code = payload.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="code is required.")
    try:
        result = await store.exchange_code_for_token(code)
        return {"status": "success", **result}
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me")
async def me(user: dict = Depends(require_user)):
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "created_at": user["created_at"],
        }
    }


@router.post("/logout")
async def logout(
    user: dict = Depends(require_user),
    authorization: str | None = Header(default=None),
):
    _, _, token = (authorization or "").partition(" ")
    if token:
        await store.revoke_token(token)
    return {"status": "success", "message": "Token revoked."}
