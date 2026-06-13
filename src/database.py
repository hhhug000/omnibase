import os
from databases import Database
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///omnibase.db")
db = Database(DATABASE_URL)

async def init_database():
    await db.connect()
    print(f"Connected to database type: {db.url.scheme}")

async def close_database():
    await db.disconnect()