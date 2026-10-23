"""Exercise authenticated jobs through the real gateway/worker containers."""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:18080")
COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.ci.yml"
COMPOSE = ["docker", "compose", "-f", str(COMPOSE_FILE)]


def request(path, method="GET", body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def wait_for_job(job_id, token, expected="succeeded", timeout=30):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = request(f"/api/jobs/{job_id}", token=token)
        if last["status"] == expected:
            return last
        if last["status"] in {"failed", "cancelled"}:
            raise AssertionError(f"job ended unexpectedly: {last['status']}")
        time.sleep(0.25)
    raise AssertionError(f"job did not reach {expected}; last response: {last}")


def submit(token, prompt):
    return request("/api/jobs", "POST", {"prompt": prompt, "max_tokens": 16}, token)


def main():
    ready_until = time.monotonic() + 45
    while True:
        try:
            request("/ready")
            break
        except (urllib.error.URLError, TimeoutError):
            if time.monotonic() >= ready_until:
                raise
            time.sleep(1)

    session = request("/api/auth/session", "POST", {
        "email": "container-smoke@example.invalid",
        "password": "ci-only-password-not-a-secret",
    })
    token = session["access_token"]
    first = submit(token, "synthetic integration check one")
    result = wait_for_job(first["jobId"], token)
    assert result["result"]["content"] == "Synthetic CI fixture response."
    assert result["result"]["completion_tokens"] == 4

    subprocess.run(COMPOSE + ["stop", "worker"], check=True, capture_output=True, text=True)
    try:
        queued = submit(token, "synthetic integration check across restart")
        stored = request(f"/api/jobs/{queued['jobId']}", token=token)
        assert stored["status"] == "queued", stored
    finally:
        subprocess.run(COMPOSE + ["start", "worker"], check=True, capture_output=True, text=True)

    recovered = wait_for_job(queued["jobId"], token)
    assert recovered["result"]["completion_tokens"] == 4
    usage = request("/api/usage", token=token)
    assert usage["actual_tokens"] == 8, usage
    print("container gateway auth, durable queue, worker restart, and usage accounting passed")


if __name__ == "__main__":
    main()
