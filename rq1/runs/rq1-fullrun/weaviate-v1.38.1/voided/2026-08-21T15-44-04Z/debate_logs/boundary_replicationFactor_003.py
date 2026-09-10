#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: replicationConfig.replicationFactor — 合法值 rf=3 被静默丢弃（persist factor=1，无 4xx）
+ 非法值（0/-1/1.5/"3"/16384/null）全部静默归一化，无类型/范围校验
Constraint: weaviate_type_create_collection_004 (replicationFactor integer)
实测锚点：别名键 "factor":3 → 正确 422 "could not find enough weaviate nodes for
replication: 1 available, 3 requested"（说明服务端有校验能力，但 "replicationFactor"
键被 silent-drop 绕过）。
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

def unit(tag, cfg):
    name = f"BndRep_{tag}"
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    s, b, t = safe_request("POST", "/v1/schema", json={
        "class": name, "vectorizer": "none", "replicationConfig": cfg})
    rb = None
    gs, gb, _ = safe_request("GET", f"/v1/schema/{name}")
    if gs == 200 and gb: rb = (gb.get("replicationConfig") or {}).get("factor")
    print(f"[{tag}] cfg={cfg!r} -> create={s} persisted_factor={rb!r} err={t[:120] if s!=200 else ''}")
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    return s, rb

unit("alias3", {"factor": 3})          # anchor: expect 422 (validation exists for alias key)
cs, crb = unit("ctrl", {"replicationFactor": 1})  # control: rf=1 -> factor 1
res = [unit(t, {"replicationFactor": v}) for t, v in
       [("rf3", 3), ("zero", 0), ("neg", -1), ("float", 1.5),
        ("str", "3"), ("big", 16384), ("null", None)]]

defect = False
for (tag, _), (s, rb) in zip([("rf3",3),("zero",0),("neg",-1),("float",1.5),("str","3"),("big",16384),("null",None)], res):
    if s in (200, 201):
        if tag == "rf3":
            print("DEFECT[rf3] Type1_IllegalSuccess: documented replicationFactor=3 accepted but silently dropped (factor=1, no 4xx)")
            defect = True
        elif tag in ("neg", "float", "str", "big"):
            print(f"DEFECT[{tag}] Type1_IllegalSuccess: illegal value {tag} accepted, silently normalized to factor=1")
            defect = True
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
