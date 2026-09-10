#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-5 (vein_f32_overflow_vector_13): vector components
beyond f32 range accepted (200), stored as inf/NaN, read back as null and
ranked top with null score.

Defect: PUT /points accepts vector components like 1e300 (finite f64, legal
JSON number) with 200. Read-back returns [null,null,null,null] (violates
OpenAPI vector: array of number). A normal query ranks the poisoned point
FIRST with score=null (violates ScoredPoint.score: required number),
displacing true matches. Boundary is f32::MAX=3.4028235e38.

Source: defects/defect-5.md; log output_vein_f32_overflow_vector_13.log.
"""
import os, sys, json, random
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

C = "mre_q5_f32"


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


def reproduce():
    random.seed(4)
    # Step 1: setup - clean collection, 10 normal points + poison point id=999
    safe_request("DELETE", f"/collections/{C}")
    st, _ = safe_request("PUT", f"/collections/{C}",
                         json={"vectors": {"size": 4, "distance": "Cosine"}})
    if st not in (200, 201):
        print(f"setup create failed: {st}")
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False
    pts = [{"id": j, "vector": [random.random() for _ in range(4)]} for j in range(10)]
    pts.append({"id": 999, "vector": [1e300, 1e300, 1e300, 1e300]})

    # Step 2: trigger - upsert oversized components (f64-finite, > f32 max)
    st_up, body_up = safe_request("PUT", f"/collections/{C}/points?wait=true",
                                  json={"points": pts})
    print(f"upsert with 1e300 components: Status: {st_up} "
          f"({'accepted' if st_up == 200 else body_up})")

    # Step 3: verify - read-back null components
    vec999 = vec0 = None
    st, body = safe_request("POST", f"/collections/{C}/points",
                            json={"ids": [999, 0], "with_vector": True})
    if st == 200 and isinstance(body, dict) and isinstance(body.get("result"), list):
        result = body["result"]
        if len(result) >= 2:
            vec999 = result[0].get("vector")
            vec0 = result[1].get("vector")
    print(f"read-back id=999 vector: {vec999}")
    print(f"read-back id=0   vector (control): {vec0}")
    null_components = vec999 is not None and any(v is None for v in vec999)

    # verify - normal query ranks poison point first with null score
    null_first = False
    st, body = safe_request("POST", f"/collections/{C}/points/query",
                            json={"query": [0.11, 0.22, 0.33, 0.44], "limit": 3})
    top = []
    if st == 200 and isinstance(body, dict):
        result = body.get("result", {})
        points = result.get("points", []) if isinstance(result, dict) else []
        top = [(p.get("id"), p.get("score")) for p in points]
    print(f"normal query top3: {top}")
    if top and top[0][0] == 999 and top[0][1] is None:
        null_first = True

    # verify - oversized query vector makes every score null
    all_null = False
    st, body = safe_request("POST", f"/collections/{C}/points/query",
                            json={"query": [1e300] * 4, "limit": 3})
    scores = []
    if st == 200 and isinstance(body, dict):
        result = body.get("result", {})
        points = result.get("points", []) if isinstance(result, dict) else []
        scores = [p.get("score") for p in points]
        all_null = bool(points) and all(s is None for s in scores)
    print(f"query [1e300 x4] scores: {scores}")

    # boundary around f32::MAX
    st, body = safe_request("POST", f"/collections/{C}/points/query",
                            json={"query": [3.4028235e38] * 4, "limit": 10})
    f32max_scores = []
    if st == 200 and isinstance(body, dict):
        result = body.get("result", {})
        points = result.get("points", []) if isinstance(result, dict) else []
        f32max_scores = [p.get("score") for p in points[:3]]
    st, body = safe_request("POST", f"/collections/{C}/points/query",
                            json={"query": [3.5e38] * 4, "limit": 10})
    over_scores = []
    if st == 200 and isinstance(body, dict):
        result = body.get("result", {})
        points = result.get("points", []) if isinstance(result, dict) else []
        over_scores = [p.get("score") for p in points[:3]]
    print(f"query at f32max scores: {f32max_scores} | 3.5e38 scores: {over_scores}")

    if st_up == 200 and null_components and null_first and all_null:
        print("\nVERDICT: DEFECT_REPRODUCED")
        return True
    print("\nVERDICT: NOT_REPRODUCED")
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if reproduce() else 1)
    finally:
        safe_request("DELETE", f"/collections/{C}")
