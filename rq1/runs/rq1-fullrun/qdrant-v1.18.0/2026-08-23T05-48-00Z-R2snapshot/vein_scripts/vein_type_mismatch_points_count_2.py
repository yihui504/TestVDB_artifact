# vein candidate 2: count(exact:false) returns ~half-total for filter values whose
# type mismatches the indexed field schema (match str/bool against integer index,
# match int/bool against keyword index). Exact path correctly returns 0; the
# approximate path silently substitutes an unrelated cardinality instead of 0.
# Cross-checked: scroll with same filter returns 0 points.
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

C = "vein_c2"
N = 200
try:
    safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    random.seed(7)
    for i in range(0, N, 100):
        batch = [{"id": j, "vector": [random.random() for _ in range(4)],
                  "payload": {"num": random.randint(0, 100),
                              "cat": random.choice(["a", "b", "c"])}}
                 for j in range(i, min(i + 100, N))]
        safe_request("PUT", f"/collections/{C}/points?wait=true", json={"points": batch})
    for f, t in [("num", "integer"), ("cat", "keyword")]:
        safe_request("PUT", f"/collections/{C}/index?wait=true",
                     json={"field_name": f, "field_schema": t})
    time.sleep(8)

    def count(field, value, exact):
        flt = {"must": [{"key": field, "match": {"value": value}}]}
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               json={"filter": flt, "exact": exact})
        return b["result"]["count"] if s == 200 else None

    # str against integer index
    e1, a1 = count("num", "50", True), count("num", "50", False)
    # bool against integer index
    e2, a2 = count("num", True, True), count("num", True, False)
    # int against keyword index
    e3, a3 = count("cat", 5, True), count("cat", 5, False)
    print(f"num match '50' (str): exact={e1} approx={a1}")
    print(f"num match true (bool): exact={e2} approx={a2}")
    print(f"cat match 5 (int): exact={e3} approx={a3}")
    # control group: same-typed match returns sane counts on both paths
    ec, ac = count("num", 50, True), count("num", 50, False)
    print(f"CONTROL num match 50 (int): exact={ec} approx={ac}")
    div = all(e == 0 for e in (e1, e2, e3)) and all(a and a > 0.4 * N for a in (a1, a2, a3))
    if div:
        print("VERDICT: DEFECT_FOUND — approximate count silently returns ~N/2 for "
              "type-mismatched match values where exact path and scroll return 0")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
