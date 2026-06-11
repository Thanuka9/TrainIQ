"""Live smoke tests against a running TrainIQ instance (default http://127.0.0.1:5000)."""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
RESULTS = []


def record(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": passed, "detail": detail})
    mark = "PASS" if passed else "FAIL"
    line = f"  [{mark}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def get(path, follow_redirects=False):
    req = urllib.request.Request(BASE + path, method="GET")
    if not follow_redirects:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        return opener.open(req)
    return urllib.request.urlopen(req)


def post(path, data=None, headers=None):
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(BASE + path, data=data or b"{}", method="POST", headers=hdrs)
    return urllib.request.urlopen(req)


def expect_status(path, method="GET", status=200, **kwargs):
    try:
        if method == "GET":
            follow = kwargs.pop("follow_redirects", True)
            r = get(path, follow_redirects=follow)
        else:
            r = post(path, **kwargs)
        code = r.status
        body = r.read(500)
        return code, body
    except urllib.error.HTTPError as e:
        return e.code, e.read(500)


def run_http_smoke():
    print("\n=== HTTP smoke (live server) ===")
    for path in ["/", "/home", "/auth/login", "/auth/register", "/auth/onboarding", "/pricing"]:
        code, _ = expect_status(path)
        record(f"GET {path}", code == 200, f"status={code}")

    code, body = expect_status("/ping", method="POST", status=401)
    record("POST /ping without session -> 401", code == 401, f"status={code} body={body[:80]!r}")

    code, _ = expect_status("/admin/admin", follow_redirects=False)
    record("GET /admin/admin unauthenticated -> redirect", code in (301, 302, 303, 307, 308), f"status={code}")

    code, body = expect_status("/")
    record("Home page not 500", code != 500, f"status={code}")
    record("Home includes TrainIQ assets", b"trainiq" in body.lower() or b"TrainIQ" in body, "")

    try:
        r = get("/static/js/trainiq.js")
        js = r.read().decode("utf-8", errors="replace")
        record("trainiq.js served", r.status == 200, f"status={r.status}")
        record("trainiq.js has Session ping", "PING_MS" in js and "/ping" in js, "")
        record("trainiq.js has AFK warning", "WARN_MS" in js and "Still there" in js, "")
    except Exception as e:
        record("trainiq.js served", False, str(e))


def run_infra():
    print("\n=== Infrastructure ===")
    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URI", "redis://localhost:6379"), socket_connect_timeout=2)
        r.ping()
        record("Redis PING", True, os.getenv("REDIS_URI", "redis://localhost:6379"))
    except Exception as e:
        record("Redis PING", False, str(e))

    try:
        from pymongo import MongoClient
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        c = MongoClient(uri, serverSelectionTimeoutMS=3000)
        c.server_info()
        record("MongoDB connection", True, uri)
    except Exception as e:
        record("MongoDB connection", False, str(e))

    try:
        from app import app
        record("Flask app import", True, "")
    except Exception as e:
        record("Flask app import", False, str(e))


def run_pytest():
    print("\n=== pytest unit tests ===")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--ignore=tests/smoke_live.py"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    passed = proc.returncode == 0
    detail = (proc.stdout + proc.stderr).strip().split("\n")[-1]
    record("pytest tests/", passed, detail)


def main():
    print(f"Smoke target: {BASE}")
    run_infra()
    run_http_smoke()
    run_pytest()

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = sum(1 for r in RESULTS if not r["passed"])
    print(f"\n=== Summary: {passed} passed, {failed} failed ===")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
