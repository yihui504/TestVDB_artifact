#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: GraphQL Get limit 负值 — limit:-1 / -100 返回全部数据（应 4xx/校验拒绝），
对照组 limit:0 正确报错 "invalid default limit: 0"、limit:INT_MAX 正确报
"query maximum results exceeded"。负值走了与 0 相反的无校验路径。
REST 对照：GET /v1/objects?limit=-1 返回 200 空体（content-length 0，畸形响应）。
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

name = "BndLimit"
try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
s, _, t = safe_request("POST", "/v1/schema", json={
    "class": name, "vectorizer": "none", "properties": [{"name": "txt", "dataType": ["text"]}]})
if s not in (200, 201):
    print("VERDICT: SCRIPT_ERROR — setup failed"); sys.exit(2)
for i in range(3):
    safe_request("POST", "/v1/objects", json={
        "class": name, "id": f"00000000-0000-0000-0000-0000000000a{i}",
        "properties": {"txt": f"doc{i}"}})

defect = False
for lim in [0, -1, -100, 2147483647]:
    s, b, t = safe_request("POST", "/v1/graphql", json={
        "query": f"{{ Get {{ {name}(limit: {lim}) {{ txt }} }} }}"})
    got = None
    if b and b.get("data"): got = b["data"].get("Get", {}).get(name)
    print(f"[gql] limit={lim} -> {s} results={got} err={(t[:110] if 'errors' in t else '')}")
    if lim < 0 and isinstance(got, list) and len(got) > 0:
        print(f"  DEFECT Type1_IllegalSuccess: negative limit {lim} returns {len(got)} rows")
        defect = True
    if lim < 0 and "errors" not in t and (got is None):
        print(f"  DEFECT Type1_IllegalSuccess: negative limit {lim} not rejected")
        defect = True

# REST counterpart: limit=-1 returns 200 with empty body
r = requests.get(BASE_URL + f"/v1/objects?class={name}&limit=-1", timeout=30)
print(f"[rest] limit=-1 -> {r.status_code} body={r.text[:80]!r} content-length={r.headers.get('content-length')}")
if r.status_code == 200 and not r.text.strip():
    print("  DEFECT Type1_IllegalSuccess: REST limit=-1 -> 200 with empty (malformed) body")
    defect = True

try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
