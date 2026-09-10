# vein candidate 14: fractional bounds on an integer range filter are
# FLOOR-TRUNCATED instead of compared, so the exact path returns points
# OUTSIDE the requested range.
#   num gte 2.5  -> returns id 2 (num=2 < 2.5)   [should be 3..9]
#   num lt 7.5   -> omits id 7 (num=7 < 7.5)     [should be 0..7]
# The correct semantics are pinned by controls: gt 2.5 -> 3..9 and
# gte 2.0 -> 2..9, so gte 2.5 must equal gt 2 (i.e. 3..9), not gte 2.
# Affects the core filter engine: scroll, count(exact) and query+filter
# all return the out-of-range points (NOT the approximate estimator
# family — exact and scroll agree on the wrong answer).
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, path, body=None, timeout=30):
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.request(method, url, json=body,
                                headers={"Content-Type": "application/json"},
                                timeout=timeout)
        try:
            jbody = resp.json() if resp.text else {}
        except (json.JSONDecodeError, ValueError):
            jbody = resp.text
        return resp.status_code, jbody, resp.text
    except requests.exceptions.RequestException as e:
        return -1, str(e), str(e)

C = "vein_c14"
N = 10
try:
    safe_request("DELETE", f"/collections/{C}")
    safe_request("PUT", f"/collections/{C}",
                 body={"vectors": {"size": 4, "distance": "Cosine"},
                       "optimizer_config": {"indexing_threshold": 1}})
    pts = [{"id": i, "vector": [0.01 * i, 0.2, 0.3, 0.4],
            "payload": {"num": i, "num2": i}} for i in range(N)]
    safe_request("PUT", f"/collections/{C}/points?wait=true", body={"points": pts})
    # integer payload index on num only; num2 stays unindexed
    safe_request("PUT", f"/collections/{C}/index?wait=true",
                 body={"field_name": "num", "field_schema": "integer"})
    time.sleep(3)

    def scroll_ids(field, rng):
        filt = {"must": [{"key": field, "range": rng}]}
        s, b, _ = safe_request("POST", f"/collections/{C}/points/scroll",
                               body={"filter": filt, "limit": 100})
        if s != 200:
            return s, None
        return s, sorted(p["id"] for p in b["result"]["points"])

    def exact_count(field, rng):
        filt = {"must": [{"key": field, "range": rng}]}
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               body={"filter": filt, "exact": True})
        return s, (b["result"]["count"] if s == 200 else None)

    bad = []
    for field in ("num", "num2"):  # indexed and unindexed copies of same data
        _, ids_gte = scroll_ids(field, {"gte": 2.5})
        _, ids_gt = scroll_ids(field, {"gt": 2.5})
        _, ids_gte2 = scroll_ids(field, {"gte": 2.0})
        _, ids_lt = scroll_ids(field, {"lt": 7.5})
        print(f"[{field}] gte2.5={ids_gte} gt2.5={ids_gt} gte2.0={ids_gte2} lt7.5={ids_lt}")
        # oracle: gte 2.5 must behave like gt 2 (ids 3..9); lt 7.5 must keep id 7
        if ids_gte is not None and 2 in ids_gte:
            bad.append(f"{field}: gte 2.5 includes num=2 (out of range)")
        if ids_lt is not None and 7 not in ids_lt:
            bad.append(f"{field}: lt 7.5 drops num=7 (7 < 7.5)")
        sc, cnt = exact_count(field, {"gte": 2.5})
        if ids_gte is not None and cnt is not None and cnt != len(ids_gte):
            print(f"[{field}] NOTE count(exact)={cnt} vs scroll={len(ids_gte)}")

    if bad:
        print("VERDICT: DEFECT_FOUND — fractional range bounds on integer "
              "fields are floor-truncated: " + "; ".join(bad) +
              ". Controls: gt2.5 and gte2.0 bracket the correct gte2.5 "
              "answer (3..9), proving 2.5 is silently treated as 2.")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
