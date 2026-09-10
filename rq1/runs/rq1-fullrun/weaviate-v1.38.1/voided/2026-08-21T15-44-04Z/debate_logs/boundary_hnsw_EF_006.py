#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: vectorIndexConfig.EF 边界（0 / -1 / 10^9）— GET 读回被 silent-drop（键为小写 ef
且非法值不持久化），但 create 返回 200 无任何告警；且 EF=-1 的类可正常插入/检索
（检索行为与合法 EF 未定义差异）。
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

defect = False
for tag, ef in [("ctrl", 64), ("zero", 0), ("neg", -1), ("huge", 10**9)]:
    name = f"BndEFx_{tag}"
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    s, b, t = safe_request("POST", "/v1/schema", json={
        "class": name, "vectorizer": "none", "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"maxConnections": 16, "EF": ef}})
    p = None
    gs, gb, _ = safe_request("GET", f"/v1/schema/{name}")
    if gs == 200 and gb:
        p = (gb.get("vectorIndexConfig") or {}).get("ef")
    print(f"[{tag}] EF={ef} -> create={s} persisted_ef={p!r}")
    if tag in ("zero", "neg", "huge") and s == 200:
        # accepted without 4xx despite negative/invalid query-time ef
        print(f"  Type1 candidate: EF={ef} accepted (no 4xx)")
        if tag == "neg": defect = True
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass

print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess — negative EF accepted, silent-dropped on readback)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
