#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: shardingConfig.desiredCount 极大值资源极限（Type3 DoS：建类挂起→容器崩溃重启）
Constraint: weaviate_range_sharding_desired_count_001
NOTE: 实测 2147483647 导致请求 30s 超时且容器随后重启（已验证一次）。
本脚本用较小极大值 100000 再验证可重复性，避免再次崩容器后无法收尾。
"""
import requests, json, sys, os, time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:8080")

def safe_request(method, path, **kw):
    try:
        r = requests.request(method, BASE_URL + path, timeout=60, **kw)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return 0, None, str(e)

name = "BndShardDos"
try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass

t0 = time.time()
s, b, t = safe_request("POST", "/v1/schema", json={
    "class": name, "vectorizer": "none",
    "shardingConfig": {"desiredCount": 100000}})
dt = time.time() - t0
print(f"desiredCount=100000 -> {s} in {dt:.1f}s raw={t[:200]}")

if s == 0 or dt > 45:
    print("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure — huge shard count hangs create, no validation cap)")
    sys.exit(1)

# check server still alive
rs, _, _ = safe_request("GET", "/v1/.well-known/ready")
print(f"ready={rs}")
try: safe_request("DELETE", f"/v1/schema/{name}")
except Exception: pass

if s in (400, 422):
    print("VERDICT: NO_DEFECT — rejected cleanly")
elif s in (200, 201):
    print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess — 100000 shards accepted, resource-exhaustion vector)")
    sys.exit(1)
else:
    print(f"VERDICT: NO_DEFECT — unexpected status {s}")
sys.exit(0)
