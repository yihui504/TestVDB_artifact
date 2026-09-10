#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: 对象属性类型混淆 — int 属性赋 null（200 接受）vs "12"/1.5/true/[]/{}（422）。
null 被接受但语义未定义（null 会否被过滤索引/聚合跳过）。
附：id 显式空串 "" 被接受并静默生成随机 UUID（应 422）。
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

name = "BndTypeC"
try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
s, _, _ = safe_request("POST", "/v1/schema", json={
    "class": name, "vectorizer": "none",
    "properties": [{"name": "n", "dataType": ["int"]}]})
if s not in (200, 201): print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

defect = False
for v in ["12", 1.5, None, True, [], {}]:
    s, b, t = safe_request("POST", "/v1/objects", json={
        "class": name, "properties": {"n": v}})
    print(f"[int prop] n={v!r} -> {s} {t[:100] if s >= 400 else '(accepted)'}")
    if v is None and s in (200, 201):
        # 对照组（其余非法类型均 422）：null 走无校验路径
        print("  Type1 candidate: null accepted for int property")
        defect = True

# id empty string
s, b, t = safe_request("POST", "/v1/objects", json={
    "class": name, "id": "", "properties": {}})
returned_id = (b or {}).get("id") if s == 200 else None
print(f"[id ''] -> {s} returned_id={returned_id}")
if s == 200 and returned_id and returned_id != "":
    print("  DEFECT Type1_IllegalSuccess: empty-string id accepted, random UUID silently generated")
    defect = True

try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
