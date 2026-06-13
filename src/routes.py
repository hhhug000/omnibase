from fastapi import APIRouter, HTTPException, Request
from src.schema import (
    dynamic_provision_table,
    validate_identifier,
    build_where_clause,
    list_tables,
    describe_table,
    drop_table,
    add_column,
    count_rows,
)
from src.database import db

router = APIRouter(prefix="/api")

# --- HEALTH CHECK ---
@router.get("/health")
async def health_check():
    return {"status": "online", "engine": "Omnibase", "db_dialect": db.url.scheme}


# --- TABLE MANAGEMENT ---
@router.get("/tables")
async def get_tables():
    try:
        tables = await list_tables()
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tables/{table_name}/schema")
async def get_table_schema(table_name: str):
    try:
        columns = await describe_table(table_name)
        if not columns:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")
        return {"table": table_name, "columns": columns}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/tables/{table_name}")
async def delete_table(table_name: str):
    try:
        existing = await describe_table(table_name)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found.")
        await drop_table(table_name)
        return {"status": "success", "message": f"Table '{table_name}' dropped."}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tables/{table_name}/columns", status_code=201)
async def add_table_column(table_name: str, payload: dict):
    name = payload.get("name")
    col_type = payload.get("type")
    if not name or not col_type:
        raise HTTPException(status_code=400, detail="Column 'name' and 'type' are required.")
    try:
        await add_column(table_name, payload)
        return {"status": "success", "message": f"Column '{name}' added to '{table_name}'."}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 1. SCHEMA GENERATOR (Table Provisioning) ---
@router.post("/tables/create", status_code=201)
async def ui_create_table(payload: dict):
    table_name = payload.get("table_name")
    columns = payload.get("columns")
    
    if not table_name or not isinstance(columns, list):
        raise HTTPException(status_code=400, detail="Malformed structural config payload.")
    try:
        await dynamic_provision_table(table_name, columns)
        return {"status": "success", "message": f"Table '{table_name}' online."}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 2. CRUD: INSERT (Create) ---
@router.post("/db/create/{table_name}", status_code=201)
async def db_insert(table_name: str, payload: dict):
    if not payload:
        raise HTTPException(status_code=400, detail="No data provided")
        
    try:
        safe_table = validate_identifier(table_name)
        columns = [validate_identifier(k) for k in payload.keys()]
        placeholders = [f":{col}" for col in columns]
        
        query = f"INSERT INTO {safe_table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)});"
        
        await db.execute(query=query, values=payload)
        return {"status": "success"}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/db/count/{table_name}")
async def db_count(table_name: str, request: Request):
    try:
        query_params = request.query_params.multi_items()
        where_clause, params = build_where_clause(query_params)
        total = await count_rows(table_name, where_clause, params)
        return {"table": table_name, "count": total}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 3. CRUD: READ (Select) ---
@router.get("/db/read/{table_name}")
async def db_select(table_name: str, request: Request):
    try:
        safe_table = validate_identifier(table_name)
        
        # Uses .multi_items() to retain complex target parameters without overwrite drops
        query_params = request.query_params.multi_items()
        where_clause, params = build_where_clause(query_params)
        
        query = f"SELECT * FROM {safe_table} {where_clause};"
        records = await db.fetch_all(query=query, values=params)
        return [dict(row) for row in records]
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 4. CRUD: UPDATE (Modify) ---
@router.put("/db/update/{table_name}")
async def db_update(table_name: str, request: Request, payload: dict):
    if not payload: 
        raise HTTPException(status_code=400, detail="No update modifications supplied.")
        
    try:
        safe_table = validate_identifier(table_name)
        
        query_params = request.query_params.multi_items()
        where_clause, where_params = build_where_clause(query_params)
        
        if not where_clause: 
            raise HTTPException(status_code=400, detail="Targeted constraint required for updates.")
            
        set_parts = []
        update_values = {}
        for key, val in payload.items():
            safe_col = validate_identifier(key)
            param_name = f"up_{safe_col}"
            set_parts.append(f"{safe_col} = :{param_name}")
            update_values[param_name] = val
            
        update_values.update(where_params)
        query = f"UPDATE {safe_table} SET {', '.join(set_parts)} {where_clause};"
        
        await db.execute(query=query, values=update_values)
        return {"status": "success", "message": "Records updated successfully."}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- 5. CRUD: DELETE (Destroy) ---
@router.delete("/db/delete/{table_name}")
async def db_delete(table_name: str, request: Request):
    try:
        safe_table = validate_identifier(table_name)
        
        query_params = request.query_params.multi_items()
        where_clause, params = build_where_clause(query_params)
        
        if not where_clause: 
            raise HTTPException(status_code=400, detail="Targeted constraint required for deletes.")
            
        query = f"DELETE FROM {safe_table} {where_clause};"
        await db.execute(query=query, values=params)
        return {"status": "success", "message": "Records deleted successfully."}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))