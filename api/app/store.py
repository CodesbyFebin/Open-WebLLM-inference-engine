"""PostgreSQL identity, quota, audit, and durable-job store."""
from __future__ import annotations

import json
import hashlib
import hmac
import os
from pathlib import Path

from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .identity import Principal, hash_session, new_id, new_session, password_hash, verify_password

MIGRATIONS = Path(__file__).parent / "migrations"
DUMMY_PASSWORD_HASH = password_hash("invalid-placeholder-password")


class PostgresStore:
    def __init__(self, url: str, migration_url: str | None = None):
        self.url = url
        self.migration_url = migration_url
        self.pool = AsyncConnectionPool(url, min_size=1, max_size=10, open=False,
                                        kwargs={"row_factory": dict_row})

    async def open(self):
        if self.migration_url:
            await self.apply_migrations(self.migration_url)
        await self.pool.open()
        await self.pool.wait()

    @staticmethod
    async def apply_migrations(url: str):
        async with AsyncConnectionPool(url, min_size=1, max_size=1, open=False,
                                       kwargs={"row_factory": dict_row}) as pool:
            async with pool.connection() as conn:
                await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
                for migration in sorted(MIGRATIONS.glob("*.sql")):
                    async with conn.transaction():
                        await conn.execute("SELECT pg_advisory_xact_lock(1431232921)")
                        exists = await (await conn.execute(
                            "SELECT 1 FROM schema_migrations WHERE version=%s", (migration.name,)
                        )).fetchone()
                        if exists:
                            continue
                        await conn.execute(migration.read_text())
                        await conn.execute("INSERT INTO schema_migrations(version) VALUES (%s) ON CONFLICT DO NOTHING",
                                           (migration.name,))

    async def close(self):
        await self.pool.close()

    async def ping(self):
        async with self.pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True

    async def create_tenant_owner(self, tenant_name: str, email: str, password: str, daily_requests=100, daily_tokens=100000):
        tenant_id, user_id = new_id(), new_id()
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("INSERT INTO tenants(tenant_id,name) VALUES (%s,%s)", (tenant_id, tenant_name))
                await conn.execute("INSERT INTO users(user_id,tenant_id,email,password_hash,role) VALUES (%s,%s,%s,%s,'owner')",
                                   (user_id, tenant_id, email.strip().lower(), password_hash(password)))
                await self._set_tenant(conn, str(tenant_id))
                await conn.execute("INSERT INTO tenant_quotas(tenant_id,daily_requests,daily_tokens) VALUES (%s,%s,%s)",
                                   (tenant_id, daily_requests, daily_tokens))
        return {"tenant_id": str(tenant_id), "user_id": str(user_id), "email": email.strip().lower()}

    async def create_user(self, tenant_id: str, email: str, password: str, role: str = "member", actor_id: str | None = None):
        if role not in {"admin", "member", "viewer"}:
            raise ValueError("User role must be admin, member, or viewer")
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, tenant_id)
                row = await (await conn.execute(
                    "SELECT hello_create_user(%s,%s,%s,%s) AS user_id",
                    (tenant_id, email.strip().lower(), password_hash(password), role)
                )).fetchone()
                await conn.execute(
                    "INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata) "
                    "VALUES (%s,%s,'admin.user_created',%s,%s)",
                    (tenant_id, actor_id, email.strip().lower(), json.dumps({"role": role}))
                )
                user_id = row["user_id"]
        return {"user_id": str(user_id), "email": email.strip().lower(), "role": role}

    async def login(self, email: str, password: str, client_ip: str = "unknown"):
        normalized_email = email.strip().lower()
        pepper = os.getenv("AUTH_THROTTLE_PEPPER", "local-development-only-change-me")
        attempt_key = hmac.new(pepper.encode(), f"{normalized_email}|{client_ip}".encode(), hashlib.sha256).hexdigest()
        login_error = None
        async with self.pool.connection() as conn:
            async with conn.transaction():
                attempt = await (await conn.execute(
                    "SELECT locked_until FROM auth_login_attempts WHERE attempt_key=%s", (attempt_key,)
                )).fetchone()
                if attempt and attempt["locked_until"]:
                    is_locked = await (await conn.execute(
                        "SELECT %s > now() AS locked", (attempt["locked_until"],)
                    )).fetchone()
                    if is_locked["locked"]:
                        login_error = 429
                row = await (await conn.execute(
                    "SELECT u.user_id,u.tenant_id,u.password_hash,u.role FROM users u "
                    "WHERE lower(u.email)=lower(%s) AND u.disabled=false", (normalized_email,)
                )).fetchone()
                if login_error is None:
                    valid = verify_password(password, row["password_hash"]) if row else verify_password(password, DUMMY_PASSWORD_HASH)
                else:
                    valid = False
                if login_error is None and (not row or not valid):
                    failure = await (await conn.execute(
                        "INSERT INTO auth_login_attempts(attempt_key,window_started,failure_count) VALUES (%s,now(),1) "
                        "ON CONFLICT(attempt_key) DO UPDATE SET "
                        "window_started=CASE WHEN auth_login_attempts.window_started < now()-interval '15 minutes' THEN now() ELSE auth_login_attempts.window_started END, "
                        "failure_count=CASE WHEN auth_login_attempts.window_started < now()-interval '15 minutes' THEN 1 ELSE auth_login_attempts.failure_count+1 END, "
                        "locked_until=CASE WHEN (CASE WHEN auth_login_attempts.window_started < now()-interval '15 minutes' THEN 1 ELSE auth_login_attempts.failure_count+1 END) >= 5 THEN now()+interval '15 minutes' ELSE NULL END "
                        "RETURNING failure_count,locked_until", (attempt_key,)
                    )).fetchone()
                    if failure["locked_until"]:
                        login_error = 429
                    else:
                        login_error = 401
                elif login_error is None:
                    token, token_hash, expires = new_session()
                    await conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (%s,%s,%s)",
                                       (token_hash, row["user_id"], expires))
                    await self._set_tenant(conn, str(row["tenant_id"]))
                    await conn.execute(
                        "INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata) VALUES (%s,%s,'auth.session_created','session','{}'::jsonb)",
                        (row["tenant_id"], row["user_id"])
                    )
                    await conn.execute("DELETE FROM auth_login_attempts WHERE attempt_key=%s", (attempt_key,))
                    result = {"access_token": token, "token_type": "bearer", "expires_at": expires.isoformat(),
                              "role": row["role"]}
        if login_error == 429:
            raise HTTPException(429, "Too many sign-in attempts; try again later",
                                headers={"Retry-After": "900"})
        if login_error:
            raise HTTPException(401, "Invalid email or password")
        return result

    async def resolve(self, token: str) -> Principal | None:
        if not token:
            return None
        async with self.pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT u.user_id,u.tenant_id,u.role FROM sessions s JOIN users u USING(user_id) "
                "WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at>now() AND u.disabled=false",
                (hash_session(token),)
            )).fetchone()
            if not row:
                return None
            return Principal(str(row["user_id"]), str(row["tenant_id"]), row["role"], "session")

    async def revoke(self, principal: Principal, token: str):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("UPDATE sessions SET revoked_at=now() WHERE token_hash=%s AND user_id=%s AND revoked_at IS NULL",
                                   (hash_session(token), principal.user_id))
                await self._set_tenant(conn, principal.tenant_id or "")
                await conn.execute(
                    "INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata) VALUES (%s,%s,'auth.session_revoked','session','{}'::jsonb)",
                    (principal.tenant_id, principal.user_id)
                )

    async def _set_tenant(self, conn, tenant_id: str):
        await conn.execute("SELECT set_config('hello.tenant_id',%s,true)", (tenant_id,))

    async def reserve_inference(self, principal: Principal, max_tokens: int, model: str):
        if not principal.tenant_id:
            return None
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id)
                row = await (await conn.execute(
                    "INSERT INTO usage_daily(tenant_id,usage_date,request_count,reserved_tokens) "
                    "SELECT q.tenant_id,current_date,1,%s FROM tenant_quotas q WHERE q.tenant_id=%s "
                    "AND %s <= q.daily_tokens "
                    "ON CONFLICT(tenant_id,usage_date) DO UPDATE SET "
                    "request_count=usage_daily.request_count+1, "
                    "reserved_tokens=usage_daily.reserved_tokens+EXCLUDED.reserved_tokens "
                    "WHERE usage_daily.request_count < (SELECT daily_requests FROM tenant_quotas WHERE tenant_id=%s) "
                    "AND usage_daily.actual_tokens+usage_daily.reserved_tokens+EXCLUDED.reserved_tokens "
                    "<= (SELECT daily_tokens FROM tenant_quotas WHERE tenant_id=%s) "
                    "RETURNING usage_date", (max_tokens, principal.tenant_id, max_tokens,
                                              principal.tenant_id, principal.tenant_id)
                )).fetchone()
                if not row:
                    raise HTTPException(429, "Tenant daily inference quota exceeded")
                await conn.execute(
                    "INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata) VALUES (%s,%s,'inference.reserve','inference',%s)",
                    (principal.tenant_id, principal.user_id, json.dumps({"model": model, "max_tokens": max_tokens}))
                )
                return {"usage_date": row["usage_date"], "reserved_tokens": max_tokens}

    async def finish_inference(self, principal: Principal, reservation, actual_tokens: int, succeeded: bool):
        if not principal.tenant_id or reservation is None:
            return
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id)
                await conn.execute(
                    "UPDATE usage_daily SET reserved_tokens=GREATEST(0,reserved_tokens-%s), "
                    "actual_tokens=actual_tokens+%s WHERE tenant_id=%s AND usage_date=%s",
                    (reservation["reserved_tokens"], actual_tokens if succeeded else 0,
                     principal.tenant_id, reservation["usage_date"])
                )
                await conn.execute(
                    "INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata) VALUES (%s,%s,%s,'inference',%s)",
                    (principal.tenant_id, principal.user_id,
                     "inference.succeeded" if succeeded else "inference.failed",
                     json.dumps({"actual_tokens": actual_tokens if succeeded else 0}))
                )

    async def audit(self, principal: Principal, action: str, resource: str, metadata: dict | None = None):
        if not principal.tenant_id:
            return
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id)
                await conn.execute("INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata) VALUES (%s,%s,%s,%s,%s)",
                                   (principal.tenant_id, principal.user_id, action, resource, json.dumps(metadata or {})))

    async def tenant_data_count(self, principal: Principal, table: str):
        allowed = {"usage_daily", "audit_events", "jobs", "tenant_quotas"}
        if table not in allowed:
            raise ValueError("Unknown tenant table")
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id or "")
                row = await (await conn.execute(f"SELECT count(*) AS n FROM {table}")).fetchone()
                return row["n"]

    async def usage(self, principal: Principal):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id or "")
                row = await (await conn.execute(
                    "SELECT coalesce(u.request_count,0) AS requests, coalesce(u.reserved_tokens,0) AS reserved_tokens, "
                    "coalesce(u.actual_tokens,0) AS actual_tokens, q.daily_requests, q.daily_tokens "
                    "FROM tenant_quotas q LEFT JOIN usage_daily u ON u.tenant_id=q.tenant_id AND u.usage_date=current_date "
                    "WHERE q.tenant_id=%s", (principal.tenant_id,)
                )).fetchone()
                return row

    async def list_audit(self, principal: Principal, limit: int = 100):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id or "")
                rows = await (await conn.execute(
                    "SELECT event_id,actor_id,action,resource,metadata,created_at FROM audit_events "
                    "ORDER BY created_at DESC,event_id DESC LIMIT %s", (limit,)
                )).fetchall()
                return rows

    async def enqueue_job(self, principal: Principal, payload: dict, reservation: dict):
        job_id = new_id()
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id or "")
                await conn.execute(
                    "INSERT INTO jobs(job_id,tenant_id,kind,status,payload,usage_date,reserved_tokens) "
                    "VALUES (%s,%s,'inference','queued',%s,%s,%s)",
                    (job_id, principal.tenant_id, json.dumps(payload), reservation["usage_date"], reservation["reserved_tokens"])
                )
                await conn.execute(
                    "INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata) VALUES (%s,%s,'job.queued',%s,%s)",
                    (principal.tenant_id, principal.user_id, str(job_id), json.dumps({"max_tokens": payload["max_tokens"]}))
                )
        return str(job_id)

    async def get_job(self, principal: Principal, job_id: str):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id or "")
                return await (await conn.execute(
                    "SELECT job_id,kind,status,payload,result,attempt,max_attempts,available_at,created_at,updated_at "
                    "FROM jobs WHERE job_id=%s", (job_id,)
                )).fetchone()

    async def cancel_job(self, principal: Principal, job_id: str):
        async with self.pool.connection() as conn:
            async with conn.transaction():
                await self._set_tenant(conn, principal.tenant_id or "")
                row = await (await conn.execute(
                    "SELECT usage_date,reserved_tokens FROM jobs WHERE job_id=%s AND status='queued' FOR UPDATE",
                    (job_id,)
                )).fetchone()
                if not row:
                    return False
                await conn.execute("UPDATE jobs SET status='cancelled',reserved_tokens=0,updated_at=now() WHERE job_id=%s", (job_id,))
                await conn.execute(
                    "UPDATE usage_daily SET reserved_tokens=greatest(0,reserved_tokens-%s) "
                    "WHERE tenant_id=%s AND usage_date=%s",
                    (row["reserved_tokens"], principal.tenant_id, row["usage_date"])
                )
                await conn.execute(
                    "INSERT INTO audit_events(tenant_id,actor_id,action,resource,metadata) VALUES (%s,%s,'job.cancelled',%s,'{}'::jsonb)",
                    (principal.tenant_id, principal.user_id, job_id)
                )
                return True
