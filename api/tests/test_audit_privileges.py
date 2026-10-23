"""Database integration regression: runtime audit history is append-only.

Executed with disposable PostgreSQL in CI; no cloud provider is contacted.
"""
import asyncio
import os

import pytest
import psycopg
from psycopg.errors import InsufficientPrivilege

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    pytest.skip("requires disposable PostgreSQL", allow_module_level=True)


def test_runtime_role_cannot_mutate_audit_history():
    async def verify():
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            for sql in (
                "UPDATE audit_events SET action = 'tampered' WHERE false",
                "DELETE FROM audit_events WHERE false",
                "TRUNCATE TABLE audit_events",
            ):
                with pytest.raises(InsufficientPrivilege):
                    await conn.execute(sql)
                await conn.rollback()
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT has_table_privilege(current_user, 'audit_events', 'INSERT') AS can_append, "
                    "has_table_privilege(current_user, 'audit_events', 'SELECT') AS can_read"
                )
                row = await cursor.fetchone()
                assert row == (True, True)
    asyncio.run(verify())
