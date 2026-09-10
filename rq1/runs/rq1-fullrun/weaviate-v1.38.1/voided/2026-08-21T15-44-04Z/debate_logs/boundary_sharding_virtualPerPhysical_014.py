#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: shardingConfig.virtualPerPhysicalShards 边界（0 / 负 / 巨大）+ 读回验证
Constraint family: weaviate_range_sharding_desired_count_001（同配置对象）
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
    name = f"BndVPP_{tag}"
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    s, b, t = safe_request("POST", "/v1/schema", json={
        "class": name, "vectorizer": "none",
        "shardingConfig": {"virtualPerPhysicalShards": val}})
    p = None
    gs, gb, _ = safe_request("GET", f"/v1/schema/{name}")
    if gs == 200 and gb:
        p = (gb.get("shardingConfig") or {}).get("virtualPerPhysicalShards")
    print(f"[{tag}] vpps={val!r} -> create={s} persisted={p!r}"
          + (f" err={t[:110]}" if s >= 400 else ""))
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    return s, p, val

units = [("ctrl", 128), ("zero", 0), ("neg", -1), ("huge", 10**9), ("float", 2.5)]
res = [unit(*u) for u in units]
if res[0][0] not in (200, 201):
    print("VERDICT: SCRIPT_ERROR — control failed"); sys.exit(2)

defect = False
for (tag, val), (s, p, _) in zip(units, res):
    if tag == "ctrl": continue
    if s in (200, 201):
        if p == val:
            print(f"DEFECT[{tag}] Type1_IllegalSuccess: {val!r} persisted verbatim"); defect = True
        elif p is not None:
            print(f"NORM[{tag}] {val!r} -> {p!r} silently normalized")
            if tag in ("neg", "float"): defect = True
        else:
            print(f"DEFECT[{tag}] Type1_IllegalSuccess: {val!r} 2xx phantom"); defect = True
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
