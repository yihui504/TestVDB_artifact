#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: vectorIndexConfig.distance.name 枚举边界（非法值 "invalid" / 空串）
实测：非法 metric 被 200 接受且静默归一化为 "cosine"（无 4xx）。用户请求 dot/曼哈顿
度量拿到的是 cosine 语义 = 静默错误度量。对照组：vectorIndexType="HNSW" 正确 422
（同属枚举参数，一个校验一个不校验）。
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

# anchor: vectorIndexType enum is validated
for vt in ["invalid", "HNSW"]:
    s, b, t = safe_request("POST", "/v1/schema", json={
        "class": "BndVIT_anchor", "vectorizer": "none", "vectorIndexType": vt})
    print(f"[anchor] vectorIndexType={vt!r} -> {s} {t[:100] if s >= 400 else '(ACCEPTED)'}")
    if s in (200, 201): defect = True  # anchor broken
    try: safe_request("DELETE", "/v1/schema/BndVIT_anchor")
    except Exception: pass

for m in ["cosine", "dot", "invalid", ""]:
    name = f"BndMetric_{abs(hash(m)) % 100000}"
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    s, b, t = safe_request("POST", "/v1/schema", json={
        "class": name, "vectorizer": "none", "vectorIndexType": "hnsw",
        "vectorIndexConfig": {"distance": {"name": m}}})
    p = None
    gs, gb, _ = safe_request("GET", f"/v1/schema/{name}")
    if gs == 200 and gb:
        p = (gb.get("vectorIndexConfig") or {}).get("distance")
    print(f"[metric] {m!r} -> create={s} persisted_distance={p!r}")
    if m in ("invalid", "") and s in (200, 201) and p == "cosine":
        print(f"  DEFECT Type1_IllegalSuccess: illegal metric {m!r} silently normalized to cosine")
        defect = True
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass

print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
