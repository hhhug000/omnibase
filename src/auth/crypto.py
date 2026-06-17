import re
import secrets
import uuid
from argon2 import PasswordHasher
import pyotp

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_pwhasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def validate_username(username: str) -> str:
    if not _USERNAME_RE.match(username):
        raise ValueError("Username must be 3–32 characters: letters, numbers, underscores only.")
    return username


def validate_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Invalid email address.")
    return email


def validate_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return password


def hash_password(password: str) -> str:
    return _pwhasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    try:
        return _pwhasher.verify(stored, password)
    except Exception:
        return False


def generate_code() -> str:
    from src.auth.config import CODE_LENGTH

    return secrets.token_urlsafe(CODE_LENGTH)


def generate_token() -> str:
    from src.auth.config import TOKEN_LENGTH

    return secrets.token_urlsafe(TOKEN_LENGTH)


def generate_user_id() -> str:
    return str(uuid.uuid4())


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="Omnibase")


def verify_totp(secret: str, code: str) -> bool:
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False
