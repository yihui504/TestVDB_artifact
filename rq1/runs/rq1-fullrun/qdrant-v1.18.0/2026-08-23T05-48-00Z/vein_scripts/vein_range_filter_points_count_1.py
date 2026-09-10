# vein candidate 1: count(exact:false) wrong cardinality when range combines
# two same-direction bounds (lt+lte / gt+gte) on an indexed integer field.
# Estimator appears to use only one of the two same-direction bounds.
# Ground truth: count(exact:true) == scroll count; approx diverges way beyond
# tolerated estimation error, and error direction depends on bound order.
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

C = "vein_c1"
N = 200
try:
    # setup: collection with tiny indexing threshold so payload index is built
    s, b, _ = safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    random.seed(7)
    for i in range(0, N, 100):
        batch = [{"id": j, "vector": [random.random() for _ in range(4)],
                  "payload": {"num": random.randint(0, 100)}}
                 for j in range(i, min(i + 100, N))]
        safe_request("PUT", f"/collections/{C}/points?wait=true", json={"points": batch})
    safe_request("PUT", f"/collections/{C}/index?wait=true",
                 json={"field_name": "num", "field_schema": "integer"})
    time.sleep(8)

    def count(exact, rng):
        f = {"must": [{"key": "num", "range": rng}]}
        s, b, t = safe_request("POST", f"/collections/{C}/points/count",
                               json={"filter": f, "exact": exact})
        return b["result"]["count"] if s == 200 else None

    # case A: lt 50 + lte 100 — tight bound is lt(50); exact ~53% of data
    ea, aa = count(True, {"lt": 50, "lte": 100}), count(False, {"lt": 50, "lte": 100})
    # case B: gt 60 + gte 70 — tight bound is gte(70); exact ~31% of data
    eb, ab = count(True, {"gt": 60, "gte": 70}), count(False, {"gt": 60, "gte": 70})
    print(f"lt50+lte100: exact={ea} approx={aa}")
    print(f"gt60+gte70: exact={eb} approx={ab}")
    tol = lambda est, ex: abs(est - ex) <= max(2, 0.2 * ex)
    if ea is not None and aa is not None and not tol(aa, ea):
        if eb is not None and ab is not None and not tol(ab, eb):
            print("VERDICT: DEFECT_FOUND — count(exact:false) uses only one of two "
                  "same-direction range bounds; cardinality wrong in both directions")
        else:
            print("VERDICT: PARTIAL — case A diverges, case B within tolerance")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
