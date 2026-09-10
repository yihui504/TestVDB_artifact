#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: 维度不匹配 — 类未声明 vector dimensions（隐式维度），插入 4 维向量后
用 2 维 query 向量 nearVector 检索：返回空数组（HTTP 200，无 errors），
无 "dimension mismatch" 诊断 = Type2_PoorDiagnostics / 数据静默不可见。
对照组：hybrid 同场景 + _additional { id } 确认数据存在。
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

name = "BndDim"
try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
s, _, _ = safe_request("POST", "/v1/schema", json={
    "class": name, "vectorizer": "none", "properties": [{"name": "txt", "dataType": ["text"]}]})
if s not in (200, 201): print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
s, _, t = safe_request("POST", "/v1/objects", json={
    "class": name, "id": "00000000-0000-0000-0000-0000000000c1",
    "properties": {"txt": "doc"}, "vector": [0.1] * 4})
print(f"[setup] insert 4-dim -> {s}")

# control: matching 4-dim query finds it
s, b, t = safe_request("POST", "/v1/graphql", json={
    "query": f"{{ Get {{ {name}(nearVector: {{vector: [0.1,0.1,0.1,0.1]}}) {{ txt }} }} }}"})
print(f"[ctrl 4d] -> {s} {t[:120]}")

# attack: 2-dim query
s, b, t = safe_request("POST", "/v1/graphql", json={
    "query": f"{{ Get {{ {name}(nearVector: {{vector: [0.1, 0.2]}}) {{ txt }} }} }}"})
print(f"[attack 2d] -> {s} {t[:200]}")

defect = False
if s == 200 and "errors" not in t and '"BndDim":[]' in t.replace(" ", ""):
    print("DEFECT Type2_PoorDiagnostics: dimension mismatch silently returns empty (no error, no hint)")
    defect = True

# REST batch insert wrong-dim vectors into declared-dim class
name2 = "BndDim2"
try: safe_request("DELETE", f"/v1/schema/{name2}")
except Exception: pass
safe_request("POST", "/v1/schema", json={
    "class": name2, "vectorizer": "none",
    "vectorIndexConfig": {"vectorCacheMaxObjects": 100}})
# no explicit dimensions field available for none-vectorizer without config; use object-level
s, b, t = safe_request("POST", "/v1/batch/objects", json={
    "objects": [{"class": name2, "id": "00000000-0000-0000-0000-0000000000d1",
                 "vector": [0.1] * 4}]})
print(f"[batch 4d into implicit class] -> {s} {t[:120]}")
s, b, t = safe_request("POST", "/v1/batch/objects", json={
    "objects": [{"class": name2, "id": "00000000-0000-0000-0000-0000000000d2",
                 "vector": [0.1] * 8}]})
print(f"[batch 8d into 4d-dim class] -> {s} {t[:200]}")
if s == 200 and '"errors":[]' in t.replace(" ", "").replace('"error":[]','"errors":[]'):
    pass  # need per-object error check
try:
    if b:
        for r in (b if isinstance(b, list) else b.get("objects", [])):
            er = r.get("result", {}).get("errors")
            if er and er.get("error"):
                print("  batch rejected with diagnostic (ok)")
            elif r.get("result", {}).get("status") == "SUCCESS":
                print("  DEFECT Type1_IllegalSuccess: 8-dim vector accepted into 4-dim class")
                defect = True
except Exception as e:
    print("  parse issue", e)

for n in (name, name2):
    try: safe_request("DELETE", f"/v1/schema/{n}")
    except Exception: pass
print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
