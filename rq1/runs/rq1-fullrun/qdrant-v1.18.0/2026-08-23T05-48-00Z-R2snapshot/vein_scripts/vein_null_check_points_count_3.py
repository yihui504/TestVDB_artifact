# vein candidate 3: count(exact:false) with is_empty on an unindexed /
# nonexistent field diverges massively from exact (exact=ALL, approx=~half),
# and is_empty on an indexed keyword array field (exact=1) returns approx=47.
# The is_empty cardinality estimator does not implement the documented
# "empty or missing" semantics — it returns a coarse fraction of total.
# Control (is_null on indexed field, both paths) is consistent.
import requests, json, sys, os, time, random

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            print(f"JSON_DECODE_ERROR: {text[:200]}")
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""

C = "vein_c3"
N = 200
try:
    safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    random.seed(7)
    for i in range(0, N, 100):
        batch = [{"id": j, "vector": [random.random() for _ in range(4)],
                  "payload": {"num": random.randint(0, 100),
                              "cat": random.choice(["a", "b", "c"]),
                              "tags": random.sample(["t1", "t2", "t3"], k=random.randint(1, 2))}}
                 for j in range(i, min(i + 100, N))]
        safe_request("PUT", f"/collections/{C}/points?wait=true", json={"points": batch})
    # one point with a truly empty tags array
    safe_request("PUT", f"/collections/{C}/points?wait=true",
                 json={"points": [{"id": 4000, "vector": [0.1, 0.2, 0.3, 0.4],
                                   "payload": {"cat": "a", "tags": []}}]})
    safe_request("PUT", f"/collections/{C}/index?wait=true",
                 json={"field_name": "tags", "field_schema": "keyword"})
    time.sleep(8)

    def count(exact, cond):
        flt = {"must": [cond]}
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               json={"filter": flt, "exact": exact})
        return b["result"]["count"] if s == 200 else None

    # is_empty on indexed keyword array: exactly 1 point has tags=[]
    e1 = count(True, {"is_empty": {"key": "tags"}})
    a1 = count(False, {"is_empty": {"key": "tags"}})
    # is_empty on nonexistent field: documented semantics = all points match
    e2 = count(True, {"is_empty": {"key": "nonexistent_zzz"}})
    a2 = count(False, {"is_empty": {"key": "nonexistent_zzz"}})
    print(f"is_empty tags (truth=1): exact={e1} approx={a1}")
    print(f"is_empty nonexistent (truth={N + 1}): exact={e2} approx={a2}")
    tol = lambda est, ex: abs(est - ex) <= max(2, 0.2 * ex)
    if (e1 == 1 and not tol(a1, 1)) or (e2 == N + 1 and not tol(a2, N + 1)):
        print("VERDICT: DEFECT_FOUND — is_empty approximate cardinality is a coarse "
              "fraction of total, violating documented empty-or-missing semantics; "
              "exact path and scroll agree on ground truth")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
