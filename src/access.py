from fastapi import HTTPException

from src.database import db
from src.schema import OWNER_COLUMN, validate_identifier

POLICY_TABLE = "table_access_policies"
ACCESS_LEVELS = frozenset({"none", "owner", "everyone"})
OPERATIONS = ("create", "read", "update", "delete")

DEFAULT_POLICY = {
    "create": "owner",
    "read": "owner",
    "update": "owner",
    "delete": "owner",
}


def _is_sqlite() -> bool:
    return db.url.scheme.startswith("sqlite")


async def init_access_tables():
    await db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {POLICY_TABLE} (
            table_name TEXT PRIMARY KEY,
            create_access TEXT NOT NULL,
            read_access TEXT NOT NULL,
            update_access TEXT NOT NULL,
            delete_access TEXT NOT NULL
        );
        """
    )


def validate_access_level(level: str, field: str) -> str:
    if level not in ACCESS_LEVELS:
        raise ValueError(
            f"Invalid access level for '{field}': '{level}'. "
            f"Must be one of: {', '.join(sorted(ACCESS_LEVELS))}."
        )
    return level


def validate_policy(policy: dict) -> dict:
    validated = {}
    for op in OPERATIONS:
        if op not in policy:
            raise ValueError(f"Missing access policy for '{op}'.")
        validated[op] = validate_access_level(policy[op], op)
    return validated


def normalize_policy_input(policy: dict) -> dict:
    validated = {}
    for op in OPERATIONS:
        if op in policy:
            validated[op] = validate_access_level(policy[op], op)
    if not validated:
        raise ValueError("At least one access policy field is required.")
    return validated


def policy_from_row(row) -> dict:
    return {
        "create": row["create_access"],
        "read": row["read_access"],
        "update": row["update_access"],
        "delete": row["delete_access"],
    }


async def get_policy(table_name: str) -> dict | None:
    safe_table = validate_identifier(table_name)
    row = await db.fetch_one(
        query=(
            f"SELECT create_access, read_access, update_access, delete_access "
            f"FROM {POLICY_TABLE} WHERE table_name = :table_name;"
        ),
        values={"table_name": safe_table},
    )
    if not row:
        return None
    return policy_from_row(row)


async def get_effective_policy(table_name: str) -> dict:
    policy = await get_policy(table_name)
    return policy if policy is not None else dict(DEFAULT_POLICY)


async def create_policy(table_name: str, policy: dict | None = None) -> dict:
    safe_table = validate_identifier(table_name)
    validated = validate_policy({**DEFAULT_POLICY, **(policy or {})})
    await db.execute(
        query=(
            f"INSERT INTO {POLICY_TABLE} "
            f"(table_name, create_access, read_access, update_access, delete_access) "
            f"VALUES (:table_name, :create, :read, :update, :delete);"
        ),
        values={
            "table_name": safe_table,
            "create": validated["create"],
            "read": validated["read"],
            "update": validated["update"],
            "delete": validated["delete"],
        },
    )
    return validated


async def update_policy(table_name: str, partial: dict) -> dict:
    safe_table = validate_identifier(table_name)
    existing = await get_policy(table_name)
    if existing is None:
        raise ValueError(f"No access policy found for table '{table_name}'.")

    updates = normalize_policy_input(partial)
    merged = {**existing, **updates}
    await db.execute(
        query=(
            f"UPDATE {POLICY_TABLE} SET "
            f"create_access = :create, read_access = :read, "
            f"update_access = :update, delete_access = :delete "
            f"WHERE table_name = :table_name;"
        ),
        values={
            "table_name": safe_table,
            "create": merged["create"],
            "read": merged["read"],
            "update": merged["update"],
            "delete": merged["delete"],
        },
    )
    return merged


async def delete_policy(table_name: str):
    safe_table = validate_identifier(table_name)
    await db.execute(
        query=f"DELETE FROM {POLICY_TABLE} WHERE table_name = :table_name;",
        values={"table_name": safe_table},
    )


def is_admin(user: dict | None) -> bool:
    return bool(user and user.get("is_admin"))


def enforce_access(policy: dict, operation: str, user: dict | None):
    level = policy.get(operation, DEFAULT_POLICY[operation])
    if level == "none":
        raise HTTPException(status_code=403, detail=f"{operation.capitalize()} access denied.")
    if level == "owner" and not user:
        raise HTTPException(status_code=401, detail="Authentication required.")


def append_owner_filter(where_clause: str, params: dict, user_id: str) -> tuple[str, dict]:
    owner_clause = f"{OWNER_COLUMN} = :_access_owner_id"
    params = {**params, "_access_owner_id": user_id}
    if where_clause:
        return f"{where_clause} AND {owner_clause}", params
    return f"WHERE {owner_clause}", params


def apply_read_filter(policy: dict, where_clause: str, params: dict, user: dict | None) -> tuple[str, dict]:
    if policy.get("read") == "owner" and user:
        return append_owner_filter(where_clause, params, user["id"])
    return where_clause, params


def apply_write_filter(policy: dict, operation: str, where_clause: str, params: dict, user: dict | None) -> tuple[str, dict]:
    if policy.get(operation) == "owner" and user:
        return append_owner_filter(where_clause, params, user["id"])
    return where_clause, params
