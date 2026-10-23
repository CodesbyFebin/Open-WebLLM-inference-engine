"""Create the initial tenant owner using a migration/admin connection.

Run only from a trusted operator shell. The password is prompted without echo
and neither it nor an access token is written to stdout.
"""
import asyncio
import getpass
import os

from .store import PostgresStore


async def main():
    url = os.getenv("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("MIGRATION_DATABASE_URL must be set to the restricted bootstrap connection")
    tenant = input("Tenant name: ").strip()
    email = input("Owner email: ").strip()
    password = getpass.getpass("Owner password (12+ characters): ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match")
    store = PostgresStore(url)
    await store.open()
    try:
        result = await store.create_tenant_owner(tenant, email, password)
        print(f"Created tenant {result['tenant_id']} and owner {result['email']}")
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
