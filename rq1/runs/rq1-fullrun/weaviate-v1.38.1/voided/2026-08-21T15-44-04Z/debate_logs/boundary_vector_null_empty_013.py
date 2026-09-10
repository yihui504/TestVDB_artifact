#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: 对象 vector 字段边界 — null vector / 空数组 vector / 整型向量
实测预期：vector=null 与 vector=[] 均被 200 接受（无向量对象进入索引，
后续 nearVector 检索行为未定义）；[1,2] 整型向量也被接受（应要求 float）。
对照组：vector="abc" 正确 400。
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

name = "BndVec"
try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
s, _, _ = safe_request("POST", "/v1/schema", json={"class": name, "vectorizer": "none"})
if s not in (200, 201): print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

defect = False
cases = [("null", {"vector": None}, "00000000-0000-0000-0000-0000000000aa"),
         ("empty", {"vector": []}, "00000000-0000-0000-0000-0000000000ab"),
         ("intvec", {"vector": [1, 2]}, "00000000-0000-0000-0000-0000000000ac"),
         ("strvec", {"vector": "abc"}, "00000000-0000-0000-0000-0000000000ad")]
for tag, extra, oid in cases:
    s, b, t = safe_request("POST", "/v1/objects", json={
        "class": name, "id": oid, **extra})
    print(f"[{tag}] -> {s} {t[:110] if s >= 400 else '(accepted)'}")
    if tag == "strvec" and s in (200, 201):
        print("  CONTROL ANOMALY: string vector accepted"); defect = True
    if tag in ("null", "empty") and s in (200, 201):
        print(f"  Type1 candidate: {tag} vector accepted")
        defect = True

# readback persisted vector
gs, gb, _ = safe_request("GET", f"/v1/objects/{name}/00000000-0000-0000-0000-0000000000ac")
if gs == 200 and gb is not None:
    print(f"[intvec readback] vector={json.dumps(gb.get('vector'))}")

try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
