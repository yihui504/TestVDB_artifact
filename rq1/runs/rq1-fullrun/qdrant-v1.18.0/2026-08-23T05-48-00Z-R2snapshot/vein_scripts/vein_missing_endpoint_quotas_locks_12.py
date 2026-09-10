# vein candidate 12: documented 1.18.x service endpoints /quotas (GET/PUT) and
# /locks (GET/POST) return 404 with an empty body. Both are present in the
# structured contract (quotas+get/quotas+set/locks+get/locks+set) with schemas
# and behavioral constraints ("GET /quotas + PUT /quotas (1.18 node-wide quotas
# replacing deprecated strict-mode max_resident_memory_percent)").
# Control: sibling service endpoints GET / and GET /healthz respond 200,
# proving the service route family is mounted.
import requests, json, sys, os

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, path, body=None, timeout=15):
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.request(method, url, json=body,
                                headers={"Content-Type": "application/json"},
                                timeout=timeout)
        try:
            body = resp.json() if resp.text else {}
        except (json.JSONDecodeError, ValueError):
            body = resp.text
        return resp.status_code, body, resp.text
    except requests.exceptions.RequestException as e:
        return -1, str(e), str(e)

try:
    documented = [
        ("GET", "/quotas", None),
        ("PUT", "/quotas", {"enabled": False}),
        ("GET", "/locks", None),
        ("POST", "/locks", {"write": False}),
    ]
    statuses = {}
    for method, path, body in documented:
        s, b, t = safe_request(method, path, body=body)
        statuses[f"{method} {path}"] = (s, t.strip()[:60])
        print(f"{method} {path}: {s} body={t.strip()[:60]!r}")
    # controls: mounted service routes
    s_root, _, _ = safe_request("GET", "/")
    s_hz, _, _ = safe_request("GET", "/healthz")
    print(f"control GET /: {s_root} | control GET /healthz: {s_hz}")

    all_missing = all(s == 404 for s, _ in statuses.values())
    controls_ok = s_root == 200 and s_hz == 200
    if all_missing and controls_ok:
        print("VERDICT: DEFECT_FOUND — contract-documented endpoints "
              "GET/PUT /quotas and GET/POST /locks are absent (404 empty body) "
              "while sibling service routes respond 200; node-wide quota API "
              "(the documented replacement for deprecated strict-mode "
              "max_resident_memory_percent) is unreachable")
    elif all_missing:
        print("VERDICT: PARTIAL — endpoints 404 but controls also failing")
    else:
        print("VERDICT: NO_DEFECT — some documented endpoints respond")
finally:
    # safety: never leave a write lock on the shared DB even if a variant path
    # unexpectedly succeeded during probing
    try:
        safe_request("POST", "/locks", body={"write": False})
    except Exception:
        pass
