import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from src.database import db

ADMIN_UI_DIR = os.path.join(os.path.dirname(__file__), "admin_ui")

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    from src.auth import init_auth_tables
    from src.access import init_access_tables
    await init_auth_tables()
    await init_access_tables()
    print(f"Omnibase connected to {db.url.scheme}")
    yield
    await db.disconnect()
    print("Flushed db connections")

def create_app():
    app = FastAPI(title="Omnibase", lifespan=lifespan)

    from src.routes import router
    from src.auth import router as auth_router
    app.include_router(router)
    app.include_router(auth_router)

    app.mount("/", StaticFiles(directory=ADMIN_UI_DIR, html=True), name="admin_ui")

    return app