#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: vectorIndexConfig.dynamicEfMin/dynamicEfMax 边界 + 配对约束（efMin<=efMax）
Constraints: weaviate_type_create_collection_001/002, weaviate_range_create_collection_001
对照组: maxConnections 非法值正确 422（证明校验框架存在，dynamicEf* 未被校验）
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

def unit(tag, vic):
    name = f"BndEf_{tag}"
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    body = {"class": name, "vectorizer": "none", "vectorIndexType": "hnsw",
            "vectorIndexConfig": vic}
    s, b, t = safe_request("POST", "/v1/schema", json=body)
    pmin = pmax = None
    gs, gb, _ = safe_request("GET", f"/v1/schema/{name}")
    if gs == 200 and gb:
        c = gb.get("vectorIndexConfig") or {}
        pmin, pmax = c.get("dynamicEfMin"), c.get("dynamicEfMax")
    print(f"[{tag}] vic={vic!r} -> create={s} persisted(min={pmin!r},max={pmax!r})"
          + (f" err={t[:120]}" if s >= 400 else ""))
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    return s, pmin, pmax, vic

BASE = {"maxConnections": 16, "EF": 64}
units = [
    ("ctrl", {**BASE, "dynamicEfMin": 50, "dynamicEfMax": 100}),
    ("swap", {**BASE, "dynamicEfMin": 200, "dynamicEfMax": 100}),   # violates paired constraint
    ("minneg", {**BASE, "dynamicEfMin": -10, "dynamicEfMax": 100}),
    ("maxneg", {**BASE, "dynamicEfMin": 10, "dynamicEfMax": -5}),
    ("bothzero", {**BASE, "dynamicEfMin": 0, "dynamicEfMax": 0}),
    ("mc_ctrl", {"maxConnections": 32, "EF": 64}),  # positive control: valid
    ("mc_neg", {"maxConnections": -1, "EF": 64}),   # negative control: expect 422
]
res = [unit(*u) for u in units]

defect = False
for (tag, vic), (s, pmin, pmax, _) in zip(units, res):
    if tag == "mc_neg" and s in (200, 201):
        print("CONTROL ANOMALY: maxConnections=-1 accepted"); defect = True
    if tag in ("swap", "minneg", "maxneg", "bothzero") and s in (200, 201):
        sent_min, sent_max = vic.get("dynamicEfMin"), vic.get("dynamicEfMax")
        if pmin == sent_min and pmax == sent_max:
            print(f"DEFECT[{tag}] Type1_IllegalSuccess: persisted verbatim {pmin}/{pmax} (no validation)")
            defect = True
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
