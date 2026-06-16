import argparse
import asyncio
import os
import sys

import uvicorn


async def _create_admin(username: str, email: str, password: str):
    from src.database import db
    from src.auth import init_auth_tables, create_admin_user

    await db.connect()
    await init_auth_tables()
    try:
        user = await create_admin_user(username, email, password)
        print(f"Admin user created: {user['username']} ({user['email']})")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await db.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Omnibase")
    subparsers = parser.add_subparsers(dest="command")

    admin_parser = subparsers.add_parser("create-admin", help="Create an admin user")
    admin_parser.add_argument("username")
    admin_parser.add_argument("email")
    admin_parser.add_argument("password")

    args = parser.parse_args()

    if args.command == "create-admin":
        asyncio.run(_create_admin(args.username, args.email, args.password))
    else:
        port = int(os.getenv('PORT', 5000))
        uvicorn.run("src.__init__:create_app", host="0.0.0.0", port=port, factory=True, reload=True)
