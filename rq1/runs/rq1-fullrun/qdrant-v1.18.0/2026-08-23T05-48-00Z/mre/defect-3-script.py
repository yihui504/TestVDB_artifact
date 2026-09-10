#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-3 (vein_type_mismatch_points_count_2): approximate
count (exact=false) returns N/2 constant for type-mismatched match values
where the exact path returns 0.

Defect: count with exact=false is documented as a faster approximation of
the same filter semantics. For a match value whose type mismatches the
indexed field schema (string/bool against integer index, int against
keyword index), the exact path correctly returns 0, but the approximate
path silently substitutes CardinalityEstimation::unknown(total).exp = N/2
(observed 100 for N=200). Control: same-typed match agrees on both paths.

Source: defects/defect-3.md; log output_vein_type_mismatch_points_count_2.log.
"""
import os, sys, json, time, random
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

C = "mre_q3_approx"
N = 200


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


def count(field, value, exact):
    flt = {"must": [{"key": field, "match": {"value": value}}]}
    st, body = safe_request("POST", f"/collections/{C}/points/count",
                            json={"filter": flt, "exact": exact})
    if st == 200 and isinstance(body, dict) and isinstance(body.get("result"), dict):
        return body["result"].get("count")
    return None


def reproduce():
    random.seed(7)
    # Step 1: setup - 200 points, num (integer index) + cat (keyword index)
    safe_request("DELETE", f"/collections/{C}")
    st, _ = safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    if st not in (200, 201):
        print(f"setup create failed: {st}")
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False
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

    # Step 2: trigger - type-mismatched match values on both count paths
    e1, a1 = count("num", "50", True), count("num", "50", False)  # str vs int index
    e2, a2 = count("num", True, True), count("num", True, False)  # bool vs int index
    e3, a3 = count("cat", 5, True), count("cat", 5, False)        # int vs keyword index
    print(f"num match '50' (str):  exact={e1} approx={a1}")
    print(f"num match true (bool): exact={e2} approx={a2}")
    print(f"cat match 5 (int):     exact={e3} approx={a3}")

    # Step 3: verify against same-typed control
    ec, ac = count("num", 50, True), count("num", 50, False)
    print(f"CONTROL num match 50 (int): exact={ec} approx={ac}")

    all_exact_zero = all(e == 0 for e in (e1, e2, e3))
    approx_inflated = all(a is not None and a > 0.4 * N for a in (a1, a2, a3))
    if all_exact_zero and approx_inflated:
        print("\nVERDICT: DEFECT_REPRODUCED")
        return True
    print("\nVERDICT: NOT_REPRODUCED")
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if reproduce() else 1)
    finally:
        safe_request("DELETE", f"/collections/{C}")
