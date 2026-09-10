# vein candidate 4: count(exact:false) for should/match_any OR unions on
# indexed keyword fields substantially under-counts vs exact and scroll
# (e.g. truth 158 -> approx 135; truth 200 -> approx 145), consistently
# beyond the documented estimation tolerance. Also probes OR of two match
# values on an integer index (exact 6 -> approx 6, control).
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

C = "vein_c4"
N = 200
try:
    safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    random.seed(11)
    for i in range(0, N, 100):
        batch = [{"id": j, "vector": [random.random() for _ in range(4)],
                  "payload": {"num": random.randint(0, 100),
                              "cat": random.choice(["a", "b", "c"])}}
                 for j in range(i, min(i + 100, N))]
        safe_request("PUT", f"/collections/{C}/points?wait=true", json={"points": batch})
    for f, t in [("cat", "keyword"), ("num", "integer")]:
        safe_request("PUT", f"/collections/{C}/index?wait=true",
                     json={"field_name": f, "field_schema": t})
    time.sleep(8)

    def count(exact, flt):
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               json={"filter": flt, "exact": exact})
        return b["result"]["count"] if s == 200 else None

    def scroll_count(flt):
        n, off = 0, None
        while True:
            body = {"filter": flt, "limit": 100, "with_payload": False}
            if off is not None:
                body["offset"] = off
            s, b, _ = safe_request("POST", f"/collections/{C}/points/scroll", json=body)
            if s != 200 or b is None:
                return None
            n += len(b["result"]["points"])
            off = b["result"].get("next_page_offset")
            if off is None or n > 5000:
                return n

    flt_or = {"should": [{"key": "cat", "match": {"any": ["a", "b"]}}]}
    flt_all = {"should": [{"key": "cat", "match": {"any": ["a", "b", "c"]}}]}
    for name, flt in [("or(a,b)", flt_or), ("or(a,b,c)", flt_all)]:
        e, a, sc = count(True, flt), count(False, flt), scroll_count(flt)
        print(f"{name}: exact={e} approx={a} scroll={sc}")
        tol = abs(a - e) <= max(2, 0.2 * e) if None not in (a, e) else True
        print(f"  within tolerance: {tol}")
    # control: single-value match on both paths must agree
    flt_one = {"must": [{"key": "cat", "match": {"value": "a"}}]}
    print(f"CONTROL match(a): exact={count(True, flt_one)} approx={count(False, flt_one)}")
    verdicts = []
    for flt in (flt_or, flt_all):
        e, a = count(True, flt), count(False, flt)
        verdicts.append(None not in (e, a) and abs(a - e) > max(2, 0.2 * e))
    if any(verdicts):
        print("VERDICT: DEFECT_FOUND — should/match_any OR union approximate count "
              "under-counts beyond documented estimation tolerance")
    elif verdicts:
        print("VERDICT: PARTIAL — see per-case output")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
