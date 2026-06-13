import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv
from src.database import db

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    print(f"Omnibase connected to {db.url.scheme}")
    yield
    await db.disconnect()
    print("Flushed db connections")

def create_app():
    app = FastAPI(title="Omnibase", lifespan=lifespan)

    from src.routes import router
    app.include_router(router)

    return app