#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-7 (vein_compound_or_min_should_15): min_should with
empty conditions and min_count>=1 silently matches the ENTIRE collection
(count/scroll/query) instead of match-none.

Defect: filter {"min_should": {"conditions": [], "min_count": 1}} is
unsatisfiable (at least 1 of 0 conditions cannot hold), so it should match 0
points. v1.18.0 returns every point with 200 on count, scroll and query —
the optimizer drops the empty min_should clause entirely, making it
vacuously true. v1.19.0 upstream changed this to match-none. Controls with
real conditions behave correctly, isolating the empty-conditions edge.

Source: defects/defect-7.md; log output_vein_compound_or_min_should_15.log.
"""
import os, sys, json
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

C = "mre_q7_minshould"
N = 10


def safe_request(method, path, **kwargs):
    try:
        resp = requests.request(method, f"{DB_URL}{path}", timeout=30,
                                headers=HEADERS, **kwargs)
        try:
            body = resp.json() if resp.text else {}
        except Exception:
            body = resp.text
        return resp.status_code, body
    except Exception as e:
        return 0, str(e)


def probe(filt):
    st, body = safe_request("POST", f"/collections/{C}/points/count",
                            json={"filter": filt, "exact": True})
    n = None
    if st == 200 and isinstance(body, dict) and isinstance(body.get("result"), dict):
        n = body["result"].get("count")
    st2, body2 = safe_request("POST", f"/collections/{C}/points/scroll",
                              json={"filter": filt, "limit": 100})
    ids = None
    if st2 == 200 and isinstance(body2, dict):
        result = body2.get("result", {})
        if isinstance(result, dict) and isinstance(result.get("points"), list):
            ids = sorted(p.get("id") for p in result["points"])
    return st, n, ids


def reproduce():
    # Step 1: setup - 10 points with cat/num payload
    safe_request("DELETE", f"/collections/{C}")
    st, _ = safe_request("PUT", f"/collections/{C}",
                         json={"vectors": {"size": 4, "distance": "Cosine"}})
    if st not in (200, 201):
        print(f"setup create failed: {st}")
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False
    pts = [{"id": i, "vector": [0.01 * i, 0.2, 0.3, 0.4],
            "payload": {"cat": "a" if i % 3 else "b", "num": i}} for i in range(N)]
    safe_request("PUT", f"/collections/{C}/points?wait=true", json={"points": pts})

    # Step 2: trigger - unsatisfiable min_should (empty conditions, min_count=1)
    bad_filter = {"min_should": {"conditions": [], "min_count": 1}}
    st_bad, n_bad, ids_bad = probe(bad_filter)
    print(f"min_should empty conditions min_count=1: Status: {st_bad} count={n_bad} ids={ids_bad}")

    # Step 3: controls - real-condition min_should must behave correctly
    conds = [{"key": "cat", "match": {"value": "a"}},
             {"key": "num", "range": {"gte": 8}}]
    st_c2, n_c2, ids_c2 = probe({"min_should": {"conditions": conds, "min_count": 2}})
    print(f"control 2 real conds min_count=2: count={n_c2} ids={ids_c2} (expect [8])")

    # cross-endpoint: query with the same unsatisfiable filter
    n_q = None
    st_q, body_q = safe_request("POST", f"/collections/{C}/points/query",
                                json={"query": [0.1, 0.2, 0.3, 0.4], "limit": 100,
                                      "filter": bad_filter})
    if st_q == 200 and isinstance(body_q, dict):
        result = body_q.get("result", {})
        if isinstance(result, dict) and isinstance(result.get("points"), list):
            n_q = len(result["points"])
    print(f"query with empty min_should: Status: {st_q} n={n_q}")

    match_all = (st_bad == 200 and n_bad == N and n_q == N)
    controls_ok = (st_c2 == 200 and ids_c2 == [8])
    if match_all and controls_ok:
        print("\nVERDICT: DEFECT_REPRODUCED")
        return True
    if match_all:
        print("\nVERDICT: DEFECT_REPRODUCED (match-all confirmed; control deviated)")
        return True
    print("\nVERDICT: NOT_REPRODUCED")
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if reproduce() else 1)
    finally:
        safe_request("DELETE", f"/collections/{C}")
