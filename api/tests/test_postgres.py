"""Live PostgreSQL security and consistency gates; skipped outside the PG CI job."""
import asyncio
import os
import uuid

import pytest
import httpx
from psycopg.errors import InsufficientPrivilege
from fastapi.testclient import TestClient

DATABASE_URL = os.getenv("DATABASE_URL")
MIGRATION_DATABASE_URL = os.getenv("MIGRATION_DATABASE_URL")
if not DATABASE_URL or not MIGRATION_DATABASE_URL:
    pytest.skip("requires disposable PostgreSQL service", allow_module_level=True)

os.environ["API_KEY"] = ""
os.environ["NIM_ENABLED"] = "false"
from app.main import app
from app.identity import Principal, hash_session
from app.store import PostgresStore
from app.worker import InferenceWorker


@pytest.fixture(scope="module")
def pg_app():
    with TestClient(app) as client:
        admin = PostgresStore(MIGRATION_DATABASE_URL)
        async def seed():
            await admin.open()
            first = await admin.create_tenant_owner("Acme", "owner@acme.test", "long-test-password-A1!", 2, 96)
            member = await admin.create_user(first["tenant_id"], "member@acme.test", "long-test-password-B1!", "member")
            viewer = await admin.create_user(first["tenant_id"], "viewer@acme.test", "long-test-password-C1!", "viewer")
            locked = await admin.create_user(first["tenant_id"], "locked@acme.test", "long-lock-password-G1!", "member")
            second = await admin.create_tenant_owner("Beta", "owner@beta.test", "long-test-password-D1!", 5, 256)
            await admin.close()
            return first, member, viewer, locked, second
        principals = asyncio.run(seed())
        yield client, principals


def login(client, email, password):
    response = client.post("/api/auth/session", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_sessions_expire_revoke_and_roles_are_enforced(pg_app):
    client, _ = pg_app
    owner = login(client, "owner@acme.test", "long-test-password-A1!")
    member = login(client, "member@acme.test", "long-test-password-B1!")
    viewer = login(client, "viewer@acme.test", "long-test-password-C1!")
    assert client.get("/api/auth/me", headers=bearer(owner)).json()["role"] == "owner"
    created = client.post("/api/admin/users", headers=bearer(owner), json={
        "email": "admin2@acme.test", "password": "long-admin-password-E1!", "role": "admin"})
    assert created.status_code == 201, created.text
    admin_token = login(client, "admin2@acme.test", "long-admin-password-E1!")
    assert client.post("/api/admin/users", headers=bearer(admin_token), json={
        "email": "admin3@acme.test", "password": "long-admin-password-F1!", "role": "admin"}).status_code == 403
    assert client.post("/api/benchmarks/run", headers=bearer(member),
                       json={"backend": "gpu"}).status_code == 403
    assert client.post("/api/nim/complete", headers=bearer(viewer),
                       json={"prompt": "hello"}).status_code == 403
    assert client.delete("/api/auth/session", headers=bearer(member)).status_code == 200
    assert client.get("/api/auth/me", headers=bearer(member)).status_code == 401
    assert client.post("/api/auth/session", json={"email": "owner@acme.test", "password": "incorrect-password"}).status_code == 401
    expiring = login(client, "viewer@acme.test", "long-test-password-C1!")
    admin = PostgresStore(MIGRATION_DATABASE_URL)
    async def expire():
        await admin.open()
        async with admin.pool.connection() as conn:
            await conn.execute("UPDATE sessions SET expires_at=now()-interval '1 second' WHERE token_hash=%s",
                               (hash_session(expiring),))
        await admin.close()
    asyncio.run(expire())
    assert client.get("/api/auth/me", headers=bearer(expiring)).status_code == 401
    for _ in range(5):
        blocked = client.post("/api/auth/session", json={"email": "locked@acme.test", "password": "incorrect-password"})
    assert blocked.status_code == 429
    assert client.post("/api/auth/session", json={"email": "locked@acme.test",
        "password": "long-lock-password-G1!"}).status_code == 429


def test_rls_tenant_isolation_and_audit(pg_app):
    client, _ = pg_app
    acme = login(client, "owner@acme.test", "long-test-password-A1!")
    beta = login(client, "owner@beta.test", "long-test-password-D1!")
    # NIM is explicitly disabled in this gate, so this request records a failed
    # attempt and releases the token reservation without calling an external API.
    assert client.post("/api/nim/complete", headers=bearer(acme),
                       json={"prompt": "safe qualification probe"}).status_code == 503
    usage = client.get("/api/usage", headers=bearer(acme)).json()
    assert usage["requests"] == 1
    assert usage["reserved_tokens"] == 0
    events = client.get("/api/audit", headers=bearer(acme)).json()["events"]
    assert any(event["action"] == "inference.failed" for event in events)
    beta_events = client.get("/api/audit", headers=bearer(beta)).json()["events"]
    assert not any(event["action"] == "inference.failed" for event in beta_events)
    assert client.get("/api/usage", headers=bearer(beta)).json()["requests"] == 0


def test_quota_reservation_is_atomic_under_concurrent_requests(pg_app):
    _, _identities = pg_app
    admin = PostgresStore(MIGRATION_DATABASE_URL)

    async def check():
        await admin.open()
        tenant = await admin.create_tenant_owner(
            f"Race-{uuid.uuid4()}", f"race-{uuid.uuid4()}@test.invalid",
            "long-race-password-A1!", daily_requests=1, daily_tokens=64)
        principal = Principal(tenant["user_id"], tenant["tenant_id"], "owner", "session")
        app_store = PostgresStore(DATABASE_URL)
        await app_store.open()
        try:
            outcomes = await asyncio.gather(
                app_store.reserve_inference(principal, 32, "test-model"),
                app_store.reserve_inference(principal, 32, "test-model"),
                return_exceptions=True)
            accepted = [value for value in outcomes if isinstance(value, dict)]
            rejected = [value for value in outcomes if isinstance(value, Exception)]
            assert len(accepted) == 1
            assert len(rejected) == 1
            assert getattr(rejected[0], "status_code", None) == 429
        finally:
            await app_store.close()
        await admin.close()

    asyncio.run(check())


def test_durable_worker_execution_and_crash_recovery(pg_app):
    client, _ = pg_app
    owner = login(client, "owner@beta.test", "long-test-password-D1!")
    queued = client.post("/api/jobs", headers=bearer(owner),
                         json={"prompt": "test worker output", "max_tokens": 16})
    assert queued.status_code == 202, queued.text
    job_id = queued.json()["jobId"]
    worker = InferenceWorker(os.environ["WORKER_DATABASE_URL"], os.environ["VLLM_URL"],
                             "Qwen/Qwen2.5-7B-Instruct")

    async def execute_and_recover():
        await worker.start()
        try:
            async with worker.pool.connection() as conn:
                with pytest.raises(InsufficientPrivilege):
                    await conn.execute("SELECT * FROM jobs LIMIT 1")
                await conn.rollback()
            def upstream(request):
                return httpx.Response(200, json={
                    "choices": [{"text": "A generated test answer."}],
                    "usage": {"completion_tokens": 5},
                }, request=request)
            async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as model_client:
                assert await worker.run_once(model_client) is True
            recovery = client.post("/api/jobs", headers=bearer(owner),
                                   json={"prompt": "recover after worker crash", "max_tokens": 16})
            assert recovery.status_code == 202
            recovery_id = recovery.json()["jobId"]
            first_claim = await worker.claim()
            assert str(first_claim["job_id"]) == recovery_id
            admin = PostgresStore(MIGRATION_DATABASE_URL)
            await admin.open()
            try:
                async with admin.pool.connection() as conn:
                    await conn.execute("UPDATE jobs SET lease_expires_at=now()-interval '1 second' WHERE job_id=%s", (recovery_id,))
            finally:
                await admin.close()
            reclaimed = await worker.claim()
            assert str(reclaimed["job_id"]) == recovery_id
            assert reclaimed["attempt"] == 2
            assert await worker.finish(recovery_id,
                                       {"content": "recovered result", "completion_tokens": 3}, None)
            assert await worker.claim() is None
        finally:
            await worker.close()

    asyncio.run(execute_and_recover())
    completed = client.get(f"/api/jobs/{job_id}", headers=bearer(owner))
    assert completed.status_code == 200
    assert completed.json()["status"] == "succeeded"
    assert completed.json()["result"]["completion_tokens"] == 5
    assert client.get("/api/usage", headers=bearer(owner)).json()["actual_tokens"] >= 8


def test_queued_job_cancellation_releases_reserved_tokens(pg_app):
    client, _ = pg_app
    owner = login(client, "owner@beta.test", "long-test-password-D1!")
    queued = client.post("/api/jobs", headers=bearer(owner),
                         json={"prompt": "cancel this queued job", "max_tokens": 16})
    assert queued.status_code == 202
    job_id = queued.json()["jobId"]
    assert client.delete(f"/api/jobs/{job_id}", headers=bearer(owner)).status_code == 200
    assert client.get(f"/api/jobs/{job_id}", headers=bearer(owner)).json()["status"] == "cancelled"
    assert client.get("/api/usage", headers=bearer(owner)).json()["reserved_tokens"] == 0
