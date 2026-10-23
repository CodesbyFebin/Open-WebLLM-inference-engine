"""Seed one disposable CI account using the privileged migration role."""
import asyncio
import os

from app.store import PostgresStore


async def main():
    url = os.environ["MIGRATION_DATABASE_URL"]
    store = PostgresStore(url)
    await store.open()
    try:
        await store.create_tenant_owner(
            "Disposable container smoke tenant",
            "container-smoke@example.invalid",
            "ci-only-password-not-a-secret",
        )
    finally:
        await store.close()


asyncio.run(main())
