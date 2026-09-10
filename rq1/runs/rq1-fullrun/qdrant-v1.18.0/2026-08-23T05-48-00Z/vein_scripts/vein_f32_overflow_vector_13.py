# vein candidate 13: f64->f32 silent overflow on vectors.
# The write path accepts any finite f64 component (1e300 << 1.8e308), but
# storage is f32 (max ~3.4e38): values silently become +inf.
# Consequences observed:
#   1. reading the point back returns vector components = null (JSON null)
#   2. a NORMAL query ranks the corrupted point FIRST with score = null
#      (ScoredPoint.score is documented as a number)
#   3. an oversized query vector makes every score null
# Boundary is exactly f32::MAX (3.4028235e38): 3.4028235e38 -> one null score
# (inf stored point), 3.5e38 -> all null.
# Control: ordinary points keep numeric scores in the same responses.
import requests, json, sys, os, random, time

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
            body = resp.json() if resp.text else {}
        except (json.JSONDecodeError, ValueError):
            body = resp.text
        return resp.status_code, body, resp.text
    except requests.exceptions.RequestException as e:
        return -1, str(e), str(e)

C = "vein_f32_13"
V = [0.11, 0.22, 0.33, 0.44]
try:
    safe_request("DELETE", f"/collections/{C}")
    safe_request("PUT", f"/collections/{C}",
                 body={"vectors": {"size": 4, "distance": "Cosine"}})
    random.seed(4)
    pts = [{"id": j, "vector": [random.random() for _ in range(4)]} for j in range(10)]
    pts.append({"id": 999, "vector": [1e300, 1e300, 1e300, 1e300]})  # f64-finite, > f32 max
    s_up, b_up, _ = safe_request("PUT", f"/collections/{C}/points?wait=true",
                                 body={"points": pts})
    print(f"upsert with 1e300 components: {s_up} "
          f"({'accepted' if s_up == 200 else str(b_up)[:80]})")

    # 1. read back the stored vector
    s, b, _ = safe_request("POST", f"/collections/{C}/points",
                           body={"ids": [999, 0], "with_vector": True})
    vec999 = b["result"][0].get("vector")
    vec0 = b["result"][1].get("vector")
    print(f"read-back id=999 vector: {vec999}")
    print(f"read-back id=0   vector (control): {vec0}")

    # 2. normal query: corrupted point ranked first with null score
    s, b, _ = safe_request("POST", f"/collections/{C}/points/query",
                           body={"query": V, "limit": 3})
    pts_out = b["result"]["points"]
    print("normal query top3:", [(p["id"], p["score"]) for p in pts_out])
    null_first = pts_out and pts_out[0]["id"] == 999 and pts_out[0]["score"] is None

    # 3. oversized query vector -> all scores null
    s, b, _ = safe_request("POST", f"/collections/{C}/points/query",
                           body={"query": [1e300] * 4, "limit": 3})
    all_null = all(p["score"] is None for p in b["result"]["points"])
    print(f"query [1e300 x4] scores: {[p['score'] for p in b['result']['points']]}")

    # 4. boundary around f32::MAX = 3.4028235e38
    s, b, _ = safe_request("POST", f"/collections/{C}/points/query",
                           body={"query": [3.4028235e38] * 4, "limit": 10})
    scores_f32max = [p["score"] for p in b["result"]["points"][:3]]
    s, b, _ = safe_request("POST", f"/collections/{C}/points/query",
                           body={"query": [3.5e38] * 4, "limit": 10})
    scores_over = [p["score"] for p in b["result"]["points"][:3]]
    print(f"query at f32max scores: {scores_f32max} | 3.5e38 scores: {scores_over}")

    if (s_up == 200 and any(v is None for v in (vec999 or []))
            and null_first and all_null):
        print("VERDICT: DEFECT_FOUND — vector components beyond f32 range silently "
              "accepted (stored as inf), read back as null components, and produce "
              "null scores ranked above exact matches; score schema violated")
    else:
        print("VERDICT: NO_DEFECT — see traces above (write rejected or scores numeric)")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
