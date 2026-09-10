# vein candidate 15: filter.min_should with EMPTY conditions and
# min_count >= 1 silently degrades to MATCH-ALL (returns every point)
# instead of 400/empty. {"min_should": {"conditions": [], "min_count": 1}}
# is unsatisfiable — zero conditions cannot cover a minimum of 1 — yet
# count/scroll/query all return the whole collection with 200.
# Controls: min_should with 2 real conditions behaves correctly
# (min_count=2 -> intersection [8]; min_count=1 -> union), and
# min_count=0 with empty conditions is a legitimate no-op.
import requests, json, sys, os

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

C = "vein_c15"
N = 10
try:
    safe_request("DELETE", f"/collections/{C}")
    safe_request("PUT", f"/collections/{C}",
                 body={"vectors": {"size": 4, "distance": "Cosine"}})
    pts = [{"id": i, "vector": [0.01 * i, 0.2, 0.3, 0.4],
            "payload": {"cat": "a" if i % 3 else "b", "num": i}} for i in range(N)]
    safe_request("PUT", f"/collections/{C}/points?wait=true", body={"points": pts})

    def probe(filt):
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               body={"filter": filt, "exact": True})
        n = b["result"]["count"] if s == 200 else None
        s2, b2, _ = safe_request("POST", f"/collections/{C}/points/scroll",
                                 body={"filter": filt, "limit": 100})
        ids = sorted(p["id"] for p in b2["result"]["points"]) if s2 == 200 else None
        return s, n, ids

    # defect case: empty conditions + min_count 1 (unsatisfiable)
    s_bad, n_bad, ids_bad = probe({"min_should": {"conditions": [], "min_count": 1}})
    print(f"min_should empty conditions min_count=1: status={s_bad} count={n_bad} ids={ids_bad}")

    # control 1: min_count=0 with empty conditions = legitimate no-op
    s_c0, n_c0, _ = probe({"min_should": {"conditions": [], "min_count": 0}})
    print(f"control min_count=0 empty: status={s_c0} count={n_c0}")

    # control 2: real conditions, min_count=2 -> both must hold -> [8]
    conds = [{"key": "cat", "match": {"value": "a"}},
             {"key": "num", "range": {"gte": 8}}]
    s_c2, n_c2, ids_c2 = probe({"min_should": {"conditions": conds, "min_count": 2}})
    print(f"control 2 real conds min_count=2: count={n_c2} ids={ids_c2} (expect [8])")

    # control 3: same conditions, min_count=1 -> union
    s_c1, n_c1, ids_c1 = probe({"min_should": {"conditions": conds, "min_count": 1}})
    print(f"control 3 real conds min_count=1: count={n_c1} ids={ids_c1} (union of cat=a and num>=8)")

    # cross-endpoint: query with the same unsatisfiable filter
    s_q, bq, _ = safe_request("POST", f"/collections/{C}/points/query",
                              body={"query": [0.1, 0.2, 0.3, 0.4], "limit": 100,
                                    "filter": {"min_should": {"conditions": [], "min_count": 1}}})
    n_q = len(bq["result"]["points"]) if s_q == 200 else None
    print(f"query with empty min_should: status={s_q} n={n_q}")

    matched_all = (s_bad == 200 and n_bad == N and n_q == N)
    controls_ok = (s_c2 == 200 and ids_c2 == [8])
    if matched_all and controls_ok:
        print("VERDICT: DEFECT_FOUND — min_should with conditions=[] and "
              "min_count=1 returns the ENTIRE collection (match-all) on "
              "count/scroll/query, though it is unsatisfiable; real-condition "
              "controls behave correctly, isolating the empty-conditions edge")
    elif matched_all:
        print("VERDICT: PARTIAL — match-all confirmed but control deviated; see counts above")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
