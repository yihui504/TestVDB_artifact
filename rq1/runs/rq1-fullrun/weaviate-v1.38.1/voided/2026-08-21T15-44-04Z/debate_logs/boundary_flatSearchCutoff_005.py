#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: vectorIndexConfig.flatSearchCutoff 边界（负值/极大 10^10）verbatim 持久化
Constraint: weaviate_type_create_collection_003 (flatSearchCutoff integer)
"""
import requests, json, sys, os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:8080")

def safe_request(method, path, **kw):
    try:
        r = requests.request(method, BASE_URL + path, timeout=30, **kw)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return 0, None, str(e)

def unit(tag, val):
    name = f"BndFlat_{tag}"
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    s, b, t = safe_request("POST", "/v1/schema", json={
        "class": name, "vectorizer": "none", "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"maxConnections": 16, "EF": 64,
                              "flatSearchCutoff": val}})
    p = None
    gs, gb, _ = safe_request("GET", f"/v1/schema/{name}")
    if gs == 200 and gb:
        p = (gb.get("vectorIndexConfig") or {}).get("flatSearchCutoff")
    print(f"[{tag}] flatSearchCutoff={val!r} -> create={s} persisted={p!r}")
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    return s, p, val

units = [("ctrl", 40000), ("neg", -1), ("zero", 0), ("huge", 10**10), ("str", "100")]
res = [unit(*u) for u in units]

defect = False
for tag, (s, p, val) in zip([u[0] for u in units], res):
    if tag == "ctrl" and s != 200:
        print("VERDICT: SCRIPT_ERROR — control failed"); sys.exit(2)
    if tag in ("neg", "huge", "str") and s in (200, 201) and p == val:
        print(f"DEFECT[{tag}] Type1_IllegalSuccess: {val!r} persisted verbatim")
        defect = True
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
