#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: nearVector certainty / distance 超语义域值（certainty ∈ [-1,1]，distance 越界）
certainty=1.5 / -0.5 与 distance=-2.0 / 5.0 均被 200 接受：
- certainty=1.5（数学上不可能）→ 空结果（静默吞数据）
- certainty=-0.5 → 返回全部（负向阈值语义反转）
- distance=-2.0（cosine 域外）→ 空结果；distance=5.0 → 全部返回
无任何 4xx/告警。
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

name = "BndCert"
try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
s, _, _ = safe_request("POST", "/v1/schema", json={
    "class": name, "vectorizer": "none", "properties": [{"name": "txt", "dataType": ["text"]}]})
if s not in (200, 201): print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
for i in range(3):
    safe_request("POST", "/v1/objects", json={
        "class": name, "id": f"00000000-0000-0000-0000-0000000000b{i}",
        "properties": {"txt": f"doc{i}"}, "vector": [0.1 * i] * 4})

def gql(where):
    s, b, t = safe_request("POST", "/v1/graphql", json={
        "query": f"{{ Get {{ {name}(nearVector: {{vector: [0.1,0.1,0.1,0.1], {where}}}) {{ txt }} }} }}"})
    got = None
    if b and b.get("data"): got = b["data"].get("Get", {}).get(name)
    return s, got, t

defect = False
for label, clause in [("ctrl", "certainty: 0.0"),
                      ("cert_gt1", "certainty: 1.5"),
                      ("cert_neg", "certainty: -0.5"),
                      ("dist_neg", "distance: -2.0"),
                      ("dist_gt1", "distance: 5.0")]:
    s, got, t = gql(clause)
    print(f"[{label}] {clause} -> {s} rows={got if got is None else len(got)}")
    if label != "ctrl" and s == 200 and "errors" not in t:
        print(f"  Type1 candidate: out-of-domain {clause} accepted silently")
        if label in ("cert_gt1", "cert_neg"): defect = True

try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
