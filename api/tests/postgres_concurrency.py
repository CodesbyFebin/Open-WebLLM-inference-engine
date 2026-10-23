"""Disposable PostgreSQL concurrency test; run only against staging fixture."""
import concurrent.futures
import os
import subprocess

TENANT = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
SQL = f"""BEGIN;
SET LOCAL ROLE openwebllm_app;
SELECT set_config('app.tenant_id','{TENANT}',true);
UPDATE control.quotas SET requests_used=requests_used+1
WHERE tenant_id='{TENANT}' AND period_start=DATE '2026-01-01'
  AND requests_used<request_limit RETURNING requests_used;
COMMIT;"""

def psql(sql: str) -> str:
    cmd = ["psql", "-h", os.getenv("PGHOST", "localhost"), "-U", "postgres",
           "-d", os.getenv("PGDATABASE", "postgres"), "-v", "ON_ERROR_STOP=1",
           "-At", "-c", sql]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
    return result.stdout

psql(f"""INSERT INTO control.quotas(tenant_id,period_start,request_limit)
VALUES ('{TENANT}', DATE '2026-01-01', 5)""")
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
    rows = list(pool.map(psql, [SQL] * 20))
completed = sum(any(line.strip() in {"1","2","3","4","5"} for line in output.splitlines()) for output in rows)
used = int(psql(f"""SELECT requests_used FROM control.quotas
WHERE tenant_id='{TENANT}' AND period_start=DATE '2026-01-01'""").strip())
assert used == 5, f"quota exceeded: {used}"
assert completed == 5, f"expected exactly five successful reservations, observed {completed}"
print("PASS: 20 concurrent reservations resulted in exactly 5 allowed allocations")
