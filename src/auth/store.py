from datetime import datetime, timedelta, timezone

from src.auth.config import CODE_TTL_SECONDS, TOKEN_TTL_SECONDS
from src.auth.crypto import generate_code, generate_token, hash_password
from src.database import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _is_sqlite() -> bool:
    return db.url.scheme.startswith("sqlite")


async def init_auth_tables():
    if _is_sqlite():
        users_id = "INTEGER PRIMARY KEY AUTOINCREMENT"
        row_id = "INTEGER PRIMARY KEY AUTOINCREMENT"
        bool_type = "INTEGER NOT NULL DEFAULT 0"
    else:
        users_id = "SERIAL PRIMARY KEY"
        row_id = "SERIAL PRIMARY KEY"
        bool_type = "BOOLEAN NOT NULL DEFAULT FALSE"

    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS auth_users (
            id {users_id},
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS auth_codes (
            id {row_id},
            code TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            used {bool_type}
        );
        """
    )
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            id {row_id},
            token TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            revoked {bool_type}
        );
        """
    )


async def _purge_expired():
    now = _iso(_utcnow())
    await db.execute("DELETE FROM auth_codes WHERE expires_at < :now OR used = 1;", values={"now": now})
    if _is_sqlite():
        await db.execute("DELETE FROM auth_tokens WHERE expires_at < :now OR revoked = 1;", values={"now": now})
    else:
        await db.execute("DELETE FROM auth_tokens WHERE expires_at < :now OR revoked = TRUE;", values={"now": now})


def _public_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


async def create_user(username: str, email: str, password: str) -> dict:
    await _purge_expired()
    created_at = _iso(_utcnow())
    password_hash = hash_password(password)
    try:
        if _is_sqlite():
            await db.execute(
                query=(
                    "INSERT INTO auth_users (username, email, password_hash, created_at) "
                    "VALUES (:username, :email, :password_hash, :created_at);"
                ),
                values={
                    "username": username,
                    "email": email,
                    "password_hash": password_hash,
                    "created_at": created_at,
                },
            )
            row = await db.fetch_one("SELECT * FROM auth_users WHERE username = :username;", values={"username": username})
        else:
            row = await db.fetch_one(
                query=(
                    "INSERT INTO auth_users (username, email, password_hash, created_at) "
                    "VALUES (:username, :email, :password_hash, :created_at) "
                    "RETURNING *;"
                ),
                values={
                    "username": username,
                    "email": email,
                    "password_hash": password_hash,
                    "created_at": created_at,
                },
            )
    except Exception as exc:
        message = str(exc).lower()
        if "unique" in message or "duplicate" in message:
            raise ValueError("Username or email is already registered.") from exc
        raise
    return _public_user(row)


async def get_user_by_login(login: str):
    login = login.strip()
    lowered = login.lower()
    return await db.fetch_one(
        query=(
            "SELECT * FROM auth_users "
            "WHERE username = :login OR email = :lowered LIMIT 1;"
        ),
        values={"login": login, "lowered": lowered},
    )


async def get_user_by_id(user_id: int):
    return await db.fetch_one(
        query="SELECT * FROM auth_users WHERE id = :user_id;",
        values={"user_id": user_id},
    )


async def issue_login_code(user_id: int) -> dict:
    await _purge_expired()
    code = generate_code()
    expires_at = _iso(_utcnow() + timedelta(seconds=CODE_TTL_SECONDS))
    await db.execute(
        query=(
            "INSERT INTO auth_codes (code, user_id, expires_at, used) "
            "VALUES (:code, :user_id, :expires_at, :used);"
        ),
        values={"code": code, "user_id": user_id, "expires_at": expires_at, "used": 0 if _is_sqlite() else False},
    )
    return {"code": code, "expires_in": CODE_TTL_SECONDS, "expires_at": expires_at}


async def exchange_code_for_token(code: str) -> dict:
    await _purge_expired()
    row = await db.fetch_one(
        query="SELECT * FROM auth_codes WHERE code = :code;",
        values={"code": code},
    )
    if not row:
        raise ValueError("Invalid or unknown code.")
    if bool(row["used"]):
        raise ValueError("Code has already been used.")
    if _parse_iso(row["expires_at"]) <= _utcnow():
        raise ValueError("Code has expired.")

    if _is_sqlite():
        await db.execute("UPDATE auth_codes SET used = 1 WHERE id = :id;", values={"id": row["id"]})
    else:
        await db.execute("UPDATE auth_codes SET used = TRUE WHERE id = :id;", values={"id": row["id"]})

    token = generate_token()
    expires_at = _iso(_utcnow() + timedelta(seconds=TOKEN_TTL_SECONDS))
    await db.execute(
        query=(
            "INSERT INTO auth_tokens (token, user_id, expires_at, revoked) "
            "VALUES (:token, :user_id, :expires_at, :revoked);"
        ),
        values={
            "token": token,
            "user_id": row["user_id"],
            "expires_at": expires_at,
            "revoked": 0 if _is_sqlite() else False,
        },
    )
    user = await get_user_by_id(row["user_id"])
    return {
        "token": token,
        "expires_in": TOKEN_TTL_SECONDS,
        "expires_at": expires_at,
        "user": _public_user(user),
    }


async def resolve_token(token: str) -> dict:
    await _purge_expired()
    row = await db.fetch_one(
        query="SELECT * FROM auth_tokens WHERE token = :token;",
        values={"token": token},
    )
    if not row:
        raise ValueError("Invalid or unknown token.")
    if bool(row["revoked"]):
        raise ValueError("Token has been revoked.")
    if _parse_iso(row["expires_at"]) <= _utcnow():
        raise ValueError("Token has expired.")

    user = await get_user_by_id(row["user_id"])
    if not user:
        raise ValueError("User no longer exists.")
    return _public_user(user)


async def revoke_token(token: str):
    if _is_sqlite():
        await db.execute("UPDATE auth_tokens SET revoked = 1 WHERE token = :token;", values={"token": token})
    else:
        await db.execute("UPDATE auth_tokens SET revoked = TRUE WHERE token = :token;", values={"token": token})
