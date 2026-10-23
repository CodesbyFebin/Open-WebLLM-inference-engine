"""Apply versioned SQL migrations using a privileged one-shot connection."""
import asyncio
import os

from .store import PostgresStore


async def main():
    url = os.getenv("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("MIGRATION_DATABASE_URL must be set to the migration-only connection")
    await PostgresStore.apply_migrations(url)
    print("PostgreSQL migrations applied")


if __name__ == "__main__":
    asyncio.run(main())
