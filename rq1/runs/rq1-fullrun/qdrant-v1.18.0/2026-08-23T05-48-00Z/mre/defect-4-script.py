#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-4 (boundary_collections_create_03): PUT /collections
accepts illegal datatype values ('int4'/null/123) with 200 — serde untagged
fallback swallows the enum error.

Defect: constraint qdrant_type_collections_create_007 requires datatype IN
{float32, uint8, float16} (v1.18.0 openapi). datatype='int4' in single-vector
mode gets 200 result:true, but the value is silently dropped (DESCRIBE shows
no datatype field, falls back to float32 default). Same illegal value in
multi-vector mode gets a proper 400 - validation exists on the typed path,
swallowed on the untagged fallback path.

Source: defects/defect-4.md; log output_boundary_collections_create_03.log.
"""
import os, sys, json
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

C1 = "mre_q4_int4"
C2 = "mre_q4_multi"


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


def body_str(body):
    return json.dumps(body, ensure_ascii=False) if isinstance(body, dict) else str(body)


def reproduce():
    # Step 1: clean slate
    safe_request("DELETE", f"/collections/{C1}")
    safe_request("DELETE", f"/collections/{C2}")

    # Step 2: trigger - illegal datatype 'int4' on single-vector create path
    st, body = safe_request("PUT", f"/collections/{C1}",
        json={"vectors": {"size": 4, "distance": "Cosine"}, "datatype": "int4"})
    print(f"PUT datatype='int4' (illegal): Status: {st}")
    print(f"Body: {body_str(body)}")
    accepted = (st == 200)

    # Step 3: verify config was silently dropped (DESCRIBE has no datatype)
    datatype_persisted = None
    if accepted:
        st2, desc = safe_request("GET", f"/collections/{C1}")
        if st2 == 200 and isinstance(desc, dict):
            result = desc.get("result", {})
            config = result.get("config", {})
            params = config.get("params", {})
            vectors = params.get("vectors", {})
            if isinstance(vectors, dict):
                datatype_persisted = vectors.get("datatype")
        print(f"DESCRIBE config.params.vectors.datatype = {datatype_persisted!r} "
              f"(expected by user: 'int4'; actual: dropped -> float32 default)")

    # Control: same illegal value on the typed (multi-vector) path -> proper 400
    st3, body3 = safe_request("PUT", f"/collections/{C2}",
        json={"vectors": {"v": {"size": 4, "distance": "Cosine", "datatype": "zzz"}}})
    print(f"CONTROL multi-vector datatype='zzz': Status: {st3}")
    print(f"Body: {body_str(body3)}")

    if accepted and datatype_persisted is None and st3 == 400:
        print("\nVERDICT: DEFECT_REPRODUCED")
        return True
    print("\nVERDICT: NOT_REPRODUCED")
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if reproduce() else 1)
    finally:
        safe_request("DELETE", f"/collections/{C1}")
        safe_request("DELETE", f"/collections/{C2}")
