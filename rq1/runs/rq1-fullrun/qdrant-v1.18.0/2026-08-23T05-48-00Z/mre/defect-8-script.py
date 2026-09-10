#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-8 (vein_type_mismatch_async_upsert_17): async writes
(wait=false) skip validation feedback entirely — invalid vectors are
200-acknowledged then silently dropped.

Defect: identical invalid payloads (empty vector, wrong dim) split on the wait
parameter: wait=true -> 400 "Vector dimension error"; wait=false -> 200
{"status":"acknowledged"}, then the write is permanently dropped (readback
shows only the valid control point). Affects upsert, update_vectors, batch.
Doc "400 invalid payload/vector dim mismatch" has no wait qualifier.

Source: defects/defect-8.md; log output_vein_type_mismatch_async_upsert_17.log.
"""
import os, sys, json, time
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

C = "mre_q8_async"


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
    # Step 1: setup - collection with one valid point
    safe_request("DELETE", f"/collections/{C}")
    st, _ = safe_request("PUT", f"/collections/{C}",
                         json={"vectors": {"size": 4, "distance": "Cosine"}})
    if st not in (200, 201):
        print(f"setup create failed: {st}")
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False
    safe_request("PUT", f"/collections/{C}/points?wait=true",
                 json={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})

    # Step 2: trigger - paired wait=true / wait=false on identical invalid payloads
    invalid = {
        "empty vector []": [{"id": 10, "vector": []}],
        "wrong dim 3":     [{"id": 11, "vector": [0.1, 0.2, 0.3]}],
        "wrong dim 5":     [{"id": 12, "vector": [0.1, 0.2, 0.3, 0.4, 0.5]}],
        "named empty":     [{"id": 13, "vector": {"default": []}}],
    }
    split = []
    for label, pts in invalid.items():
        st_t, _ = safe_request("PUT", f"/collections/{C}/points?wait=true",
                               json={"points": pts})
        st_f, _ = safe_request("PUT", f"/collections/{C}/points?wait=false",
                               json={"points": pts})
        print(f"{label}: wait=true -> {st_t} | wait=false -> {st_f}")
        if st_t == 400 and st_f == 200:
            split.append(label)

    # valid control on async path
    st_v, _ = safe_request("PUT", f"/collections/{C}/points?wait=false",
                           json={"points": [{"id": 99, "vector": [0.9, 0.8, 0.7, 0.6]}]})
    # update_vectors and batch endpoints, same split
    st_ut, _ = safe_request("PUT", f"/collections/{C}/points/vectors?wait=true",
                            json={"points": [{"id": 1, "vector": [1, 2]}]})
    st_uf, _ = safe_request("PUT", f"/collections/{C}/points/vectors?wait=false",
                            json={"points": [{"id": 1, "vector": [1, 2]}]})
    st_bt, _ = safe_request("POST", f"/collections/{C}/points/batch?wait=true",
                            json={"operations": [{"upsert": {"points": [{"id": 20, "vector": []}]}}]})
    st_bf, _ = safe_request("POST", f"/collections/{C}/points/batch?wait=false",
                            json={"operations": [{"upsert": {"points": [{"id": 21, "vector": []}]}}]})
    print(f"update_vectors dim2: wait=true -> {st_ut} | wait=false -> {st_uf}")
    print(f"batch empty vector:  wait=true -> {st_bt} | wait=false -> {st_bf}")

    # Step 3: verify permanent silent drop after async settle
    time.sleep(2)
    st, body = safe_request("POST", f"/collections/{C}/points",
                            json={"ids": [10, 11, 12, 13, 20, 21, 99], "with_vector": True})
    landed = None
    if st == 200 and isinstance(body, dict) and isinstance(body.get("result"), list):
        landed = sorted(p["id"] for p in body["result"])
    print(f"readback after 2s: landed ids={landed} (invalid writes 10-21 silently dropped; valid control 99 landed)")

    st1, body1 = safe_request("POST", f"/collections/{C}/points",
                              json={"ids": [1], "with_vector": True})
    vec1 = None
    if st1 == 200 and isinstance(body1, dict) and isinstance(body1.get("result"), list) and body1["result"]:
        vec1 = body1["result"][0].get("vector")
    vec_intact = vec1 is not None and len(vec1) == 4
    print(f"point 1 vector after async bad update_vectors: {vec1} (unchanged, {len(vec1) if vec1 else 0} components)")

    if (len(split) == len(invalid) and landed == [99] and vec_intact
            and st_ut == 400 and st_uf == 200 and st_bt == 400 and st_bf == 200 and st_v == 200):
        print("\nVERDICT: DEFECT_REPRODUCED")
        return True
    if split:
        print("\nVERDICT: NOT_REPRODUCED (partial split observed; see lines above)")
        return False
    print("\nVERDICT: NOT_REPRODUCED")
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if reproduce() else 1)
    finally:
        safe_request("DELETE", f"/collections/{C}")
