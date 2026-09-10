# vein candidate 17: vector validation is SKIPPED on every async
# (wait=false) write path. Identical invalid payloads get:
#   wait=true  -> 400 with precise error ("Vector dimension error:
#                  expected dim: 4, got 0/3/5")
#   wait=false -> 200 {"status":"acknowledged"} ... then the operation is
#                 SILENTLY DROPPED (point never appears; vector unchanged)
# Affected: PUT /points (upsert), POST /points/batch (upsert op),
# PUT /points/vectors (update_vectors) — for empty vector [], wrong
# dimension (3 and 5), and named-vector variants.
# Note: a by_design entry covers "wait=false operation fails, error only in
# logs"; the finding here is narrower and structural — the dimension check
# that DOES run synchronously when wait=true is simply not executed before
# enqueueing when wait=false, so async clients can never learn their writes
# are invalid.
# Controls: (a) each invalid payload 400s with wait=true; (b) a VALID
# upsert with wait=false lands and is readable (async path itself works).
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

C = "vein_c17"
try:
    safe_request("DELETE", f"/collections/{C}")
    safe_request("PUT", f"/collections/{C}",
                 body={"vectors": {"size": 4, "distance": "Cosine"}})
    safe_request("PUT", f"/collections/{C}/points?wait=true",
                 body={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})

    invalid = {
        "empty vector []":     [{"id": 10, "vector": []}],
        "wrong dim 3":         [{"id": 11, "vector": [0.1, 0.2, 0.3]}],
        "wrong dim 5":         [{"id": 12, "vector": [0.1, 0.2, 0.3, 0.4, 0.5]}],
        "named empty":         [{"id": 13, "vector": {"default": []}}],
    }
    acked_dropped = []
    for label, pts in invalid.items():
        st, _, _ = safe_request("PUT", f"/collections/{C}/points?wait=true",
                                body={"points": pts})
        sf, bf, _ = safe_request("PUT", f"/collections/{C}/points?wait=false",
                                 body={"points": pts})
        status = bf.get("result", {}).get("status") if sf == 200 else None
        print(f"{label}: wait=true -> {st} | wait=false -> {sf} ({status})")
        if st == 400 and sf == 200:
            acked_dropped.append(label)

    # valid control on the async path
    sv, _, _ = safe_request("PUT", f"/collections/{C}/points?wait=false",
                            body={"points": [{"id": 99, "vector": [0.9, 0.8, 0.7, 0.6]}]})

    # update_vectors async skip
    sut, _, _ = safe_request("PUT", f"/collections/{C}/points/vectors?wait=true",
                             body={"points": [{"id": 1, "vector": [1, 2]}]})
    suf, buf, _ = safe_request("PUT", f"/collections/{C}/points/vectors?wait=false",
                               body={"points": [{"id": 1, "vector": [1, 2]}]})
    # batch async skip
    sbt, _, _ = safe_request("POST", f"/collections/{C}/points/batch?wait=true",
                             body={"operations": [{"upsert": {"points": [{"id": 20, "vector": []}]}}]})
    sbf, _, _ = safe_request("POST", f"/collections/{C}/points/batch?wait=false",
                             body={"operations": [{"upsert": {"points": [{"id": 21, "vector": []}]}}]})
    print(f"update_vectors dim2: wait=true -> {sut} | wait=false -> {suf}")
    print(f"batch empty vector:  wait=true -> {sbt} | wait=false -> {sbf}")

    time.sleep(2)
    s, b, _ = safe_request("POST", f"/collections/{C}/points",
                           body={"ids": [10, 11, 12, 13, 20, 21, 99], "with_vector": True})
    landed = sorted(p["id"] for p in b["result"]) if s == 200 else None
    vec1 = b["result"][0].get("vector") if s == 200 and b["result"] and b["result"][0]["id"] == 1 else None
    s1, b1, _ = safe_request("POST", f"/collections/{C}/points", body={"ids": [1], "with_vector": True})
    vec1 = b1["result"][0].get("vector") if s1 == 200 and b1["result"] else None
    print(f"readback after 2s: landed ids={landed} (expect only [99])")
    print(f"point 1 vector after async bad update_vectors: {vec1} "
          f"(stored Cosine-normalized; expect 4 components, unchanged)")

    silent_drop = (landed == [99])
    vec_intact = vec1 is not None and len(vec1) == 4
    if (len(acked_dropped) == len(invalid) and silent_drop and vec_intact
            and sut == 400 and suf == 200 and sbt == 400 and sbf == 200 and sv == 200):
        print("VERDICT: DEFECT_FOUND — all async (wait=false) write paths skip "
              "vector validation: every invalid shape is 200-acknowledged then "
              "silently dropped (upsert, update_vectors, batch); identical "
              "payloads 400 with wait=true; valid async writes land (control)")
    elif acked_dropped:
        print("VERDICT: PARTIAL — asymmetry on upsert confirmed; see per-endpoint lines")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
