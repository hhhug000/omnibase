from datetime import datetime, timedelta, timezone

from src.auth.config import CODE_TTL_SECONDS, TOKEN_TTL_SECONDS
from src.auth.crypto import (
    generate_code,
    generate_token,
    generate_totp_secret,
    generate_user_id,
    hash_password,
    totp_provisioning_uri,
    verify_totp,
)
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
        row_id = "INTEGER PRIMARY KEY AUTOINCREMENT"
        bool_type = "INTEGER NOT NULL DEFAULT 0"
    else:
        row_id = "SERIAL PRIMARY KEY"
        bool_type = "BOOLEAN NOT NULL DEFAULT FALSE"

    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS auth_users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin {bool_type},
            totp_secret TEXT,
            totp_enabled {bool_type},
            created_at TEXT NOT NULL
        );
        """
    )
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS auth_codes (
            id {row_id},
            code TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
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
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked {bool_type}
        );
        """
    )
    await _migrate_auth_tables()


async def _migrate_auth_tables():
    if _is_sqlite():
        cols = await db.fetch_all("PRAGMA table_info(auth_users);")
        col_names = {row["name"] for row in cols}
        if "is_admin" not in col_names:
            await db.execute("ALTER TABLE auth_users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;")
        if "totp_secret" not in col_names:
            await db.execute("ALTER TABLE auth_users ADD COLUMN totp_secret TEXT;")
        if "totp_enabled" not in col_names:
            await db.execute("ALTER TABLE auth_users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0;")
    else:
        row = await db.fetch_one(
            query=(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'auth_users' AND column_name = 'is_admin';"
            )
        )
        if not row:
            await db.execute("ALTER TABLE auth_users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE;")
        row = await db.fetch_one(
            query=(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'auth_users' AND column_name = 'totp_secret';"
            )
        )
        if not row:
            await db.execute("ALTER TABLE auth_users ADD COLUMN totp_secret TEXT;")
        row = await db.fetch_one(
            query=(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'auth_users' AND column_name = 'totp_enabled';"
            )
        )
        if not row:
            await db.execute("ALTER TABLE auth_users ADD COLUMN totp_enabled BOOLEAN NOT NULL DEFAULT FALSE;")


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
        "totp_enabled": bool(row["totp_enabled"]) if row["totp_enabled"] is not None else False,
        "created_at": row["created_at"],
    }


def _user_from_row(row) -> dict:
    user = _public_user(row)
    user["is_admin"] = bool(row["is_admin"])
    return user


async def create_admin_user(username: str, email: str, password: str) -> dict:
    await _purge_expired()
    user_id = generate_user_id()
    created_at = _iso(_utcnow())
    password_hash = hash_password(password)
    is_admin = 1 if _is_sqlite() else True
    try:
        await db.execute(
            query=(
                "INSERT INTO auth_users (id, username, email, password_hash, is_admin, created_at) "
                "VALUES (:id, :username, :email, :password_hash, :is_admin, :created_at);"
            ),
            values={
                "id": user_id,
                "username": username,
                "email": email,
                "password_hash": password_hash,
                "is_admin": is_admin,
                "created_at": created_at,
            },
        )
        row = await db.fetch_one(
            query="SELECT * FROM auth_users WHERE id = :id;",
            values={"id": user_id},
        )
    except Exception as exc:
        message = str(exc).lower()
        if "unique" in message or "duplicate" in message:
            raise ValueError("Username or email is already registered.") from exc
        raise
    return _user_from_row(row)


async def create_user(username: str, email: str, password: str) -> dict:
    await _purge_expired()
    user_id = generate_user_id()
    created_at = _iso(_utcnow())
    password_hash = hash_password(password)
    is_admin = 0 if _is_sqlite() else False
    try:
        await db.execute(
            query=(
                "INSERT INTO auth_users (id, username, email, password_hash, is_admin, created_at) "
                "VALUES (:id, :username, :email, :password_hash, :is_admin, :created_at);"
            ),
            values={
                "id": user_id,
                "username": username,
                "email": email,
                "password_hash": password_hash,
                "is_admin": is_admin,
                "created_at": created_at,
            },
        )
        row = await db.fetch_one(
            query="SELECT * FROM auth_users WHERE id = :id;",
            values={"id": user_id},
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


async def get_user_by_id(user_id: str):
    return await db.fetch_one(
        query="SELECT * FROM auth_users WHERE id = :user_id;",
        values={"user_id": user_id},
    )


async def issue_login_code(user_id: str) -> dict:
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

    user = await get_user_by_id(row["user_id"])
    if not user:
        raise ValueError("User no longer exists.")

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
    return {
        "token": token,
        "expires_in": TOKEN_TTL_SECONDS,
        "expires_at": expires_at,
        "user": _public_user(user),
    }


async def setup_totp(user_id: str) -> dict:
    user = await get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found.")
    if bool(user["totp_enabled"]) if user["totp_enabled"] is not None else False:
        raise ValueError("TOTP is already enabled. Disable it first before setting up a new one.")
    secret = generate_totp_secret()
    uri = totp_provisioning_uri(secret, user["username"])
    await db.execute(
        "UPDATE auth_users SET totp_secret = :secret WHERE id = :id;",
        values={"secret": secret, "id": user_id},
    )
    return {"secret": secret, "uri": uri}


async def confirm_totp(user_id: str, code: str) -> dict:
    user = await get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found.")
    if bool(user["totp_enabled"]) if user["totp_enabled"] is not None else False:
        raise ValueError("TOTP is already enabled.")
    if not user["totp_secret"]:
        raise ValueError("No TOTP setup in progress. Call /totp/setup first.")
    if not verify_totp(user["totp_secret"], code):
        raise ValueError("Invalid TOTP code.")
    enabled_val = 1 if _is_sqlite() else True
    await db.execute(
        "UPDATE auth_users SET totp_enabled = :val WHERE id = :id;",
        values={"val": enabled_val, "id": user_id},
    )
    return {"totp_enabled": True}


async def disable_totp(user_id: str, code: str) -> dict:
    user = await get_user_by_id(user_id)
    if not user:
        raise ValueError("User not found.")
    if not (bool(user["totp_enabled"]) if user["totp_enabled"] is not None else False):
        raise ValueError("TOTP is not enabled.")
    if not verify_totp(user["totp_secret"], code):
        raise ValueError("Invalid TOTP code.")
    disabled_val = 0 if _is_sqlite() else False
    await db.execute(
        "UPDATE auth_users SET totp_secret = NULL, totp_enabled = :val WHERE id = :id;",
        values={"val": disabled_val, "id": user_id},
    )
    return {"totp_enabled": False}


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
    return _user_from_row(user)


async def revoke_token(token: str):
    if _is_sqlite():
        await db.execute("UPDATE auth_tokens SET revoked = 1 WHERE token = :token;", values={"token": token})
    else:
        await db.execute("UPDATE auth_tokens SET revoked = TRUE WHERE token = :token;", values={"token": token})
