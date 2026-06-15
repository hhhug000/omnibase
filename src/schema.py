import re
from src.database import db

OWNER_COLUMN = "_owner"
HIDDEN_COLUMNS = frozenset({OWNER_COLUMN})
SYSTEM_TABLES = frozenset({
    "auth_users",
    "auth_codes",
    "auth_tokens",
    "table_access_policies",
    "sqlite_sequence",
})

def validate_identifier(name: str) -> str:
    """
    Blocks SQL injection by white-listing safe alphanumeric characters.
    Rejects spaces, semicolons, dashes, and quotes entirely.
    """
    if not isinstance(name, str) or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Illegal or unsafe database identifier caught: '{name}'")
    if name in HIDDEN_COLUMNS:
        raise ValueError(f"Reserved column name: '{name}'")
    return name

def validate_data_column(name: str) -> str:
    """Like validate_identifier but allows internal system columns on write."""
    if name in HIDDEN_COLUMNS:
        return name
    return validate_identifier(name)

def translate_column_type(generic_type: str, scheme: str) -> str:
    """Maps dynamic UI types down to structural engine dialects."""
    is_sqlite = scheme.startswith("sqlite")
    mapping = {
        "id": "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY",
        "text": "TEXT",
        "integer": "INTEGER",
        "real": "REAL",
        "boolean": "INTEGER" if is_sqlite else "BOOLEAN"
    }
    return mapping.get(generic_type.lower(), "TEXT")

async def dynamic_provision_table(table_name: str, columns_spec: list):
    """Safely builds and provisions physical tables using clean identifiers."""
    safe_table = validate_identifier(table_name)
    scheme = db.url.scheme
    
    column_definitions = [f"id {translate_column_type('id', scheme)}"]
    column_definitions.append(f"{OWNER_COLUMN} TEXT")
    
    for column in columns_spec:
        col_name = validate_identifier(column["name"])
        col_type = translate_column_type(column["type"], scheme)
        null_stmt = "NOT NULL" if not column.get("nullable", True) else ""
        column_definitions.append(f"{col_name} {col_type} {null_stmt}".strip())
        
    raw_query = f"CREATE TABLE IF NOT EXISTS {safe_table} ({', '.join(column_definitions)});"
    await db.execute(query=raw_query)

async def list_tables() -> list[str]:
    scheme = db.url.scheme
    if scheme.startswith("sqlite"):
        rows = await db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%%' ORDER BY name;"
        )
        return [row["name"] for row in rows if row["name"] not in SYSTEM_TABLES]
    rows = await db.fetch_all(
        "SELECT tablename AS name FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
    )
    return [row["name"] for row in rows if row["name"] not in SYSTEM_TABLES]

async def describe_table(table_name: str, *, include_hidden: bool = False) -> list[dict]:
    safe_table = validate_identifier(table_name)
    scheme = db.url.scheme
    if scheme.startswith("sqlite"):
        rows = await db.fetch_all(f"PRAGMA table_info({safe_table});")
        columns = [
            {
                "name": row["name"],
                "type": row["type"],
                "nullable": not row["notnull"],
                "primary_key": bool(row["pk"]),
                "default": row["dflt_value"],
            }
            for row in rows
        ]
    else:
        rows = await db.fetch_all(
            query=(
                "SELECT column_name AS name, data_type AS type, is_nullable, column_default AS default_value "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table_name "
                "ORDER BY ordinal_position;"
            ),
            values={"table_name": safe_table},
        )
        columns = [
            {
                "name": row["name"],
                "type": row["type"],
                "nullable": row["is_nullable"] == "YES",
                "primary_key": False,
                "default": row["default_value"],
            }
            for row in rows
        ]
    if include_hidden:
        return columns
    return [col for col in columns if col["name"] not in HIDDEN_COLUMNS]

async def table_has_owner_column(table_name: str) -> bool:
    columns = await describe_table(table_name, include_hidden=True)
    return any(col["name"] == OWNER_COLUMN for col in columns)

def strip_hidden_fields(row: dict) -> dict:
    return {key: value for key, value in row.items() if key not in HIDDEN_COLUMNS}

async def drop_table(table_name: str):
    safe_table = validate_identifier(table_name)
    await db.execute(f"DROP TABLE IF EXISTS {safe_table};")

async def add_column(table_name: str, column: dict):
    safe_table = validate_identifier(table_name)
    col_name = validate_identifier(column["name"])
    col_type = translate_column_type(column["type"], db.url.scheme)
    null_stmt = "NOT NULL" if not column.get("nullable", True) else ""
    query = f"ALTER TABLE {safe_table} ADD COLUMN {col_name} {col_type} {null_stmt};".strip()
    await db.execute(query)

async def count_rows(table_name: str, where_clause: str = "", params: dict | None = None) -> int:
    safe_table = validate_identifier(table_name)
    query = f"SELECT COUNT(*) AS count FROM {safe_table} {where_clause};"
    row = await db.fetch_one(query=query, values=params or {})
    return row["count"]

def build_where_clause(args):
    """
    Parses dynamic sequences of query arguments safely into parameterized SQL filters.
    Accepts both dictionaries and raw sequences (like multi_items lists).
    Uses an index counter suffix to safely support multi-bound ranges (e.g. ?age=>18&age=<30).
    """
    where_parts = []
    params = {}
    
    # Normalize list-of-tuples or dictionary items to a single loop structure
    items = args if isinstance(args, (list, tuple)) else args.items()
    
    for idx, (key, value) in enumerate(items):
        safe_col = validate_identifier(key)
        
        # Parse comparison operations safely from raw parameter value bounds
        if value.startswith(">="): op, val = ">=", value[2:]
        elif value.startswith("<="): op, val = "<=", value[2:]
        elif value.startswith(">"): op, val = ">", value[1:]
        elif value.startswith("<"): op, val = "<", value[1:]
        elif value.startswith("="): op, val = "=", value[1:]
        else: op, val = "=", value
            
        param_key = f"where_{safe_col}_{idx}"
        where_parts.append(f"{safe_col} {op} :{param_key}")
        params[param_key] = val
        
    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    return where_clause, params
