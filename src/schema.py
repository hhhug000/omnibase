import re
from src.database import db

def validate_identifier(name: str) -> str:
    """
    Blocks SQL injection by white-listing safe alphanumeric characters.
    Rejects spaces, semicolons, dashes, and quotes entirely.
    """
    if not isinstance(name, str) or not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        raise ValueError(f"Illegal or unsafe database identifier caught: '{name}'")
    return name

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
    
    for column in columns_spec:
        col_name = validate_identifier(column["name"])
        col_type = translate_column_type(column["type"], scheme)
        null_stmt = "NOT NULL" if not column.get("nullable", True) else ""
        column_definitions.append(f"{col_name} {col_type} {null_stmt}".strip())
        
    raw_query = f"CREATE TABLE IF NOT EXISTS {safe_table} ({', '.join(column_definitions)});"
    await db.execute(query=raw_query)

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