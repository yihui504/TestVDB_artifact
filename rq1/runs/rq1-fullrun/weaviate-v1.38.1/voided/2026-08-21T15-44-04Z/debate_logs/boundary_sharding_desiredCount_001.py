#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: shardingConfig.desiredCount 边界值（0 / -1 / 小数 / 字符串 / 极大值）+ 读回验证
Constraint: weaviate_range_sharding_desired_count_001 (desiredCount >= 1)
"""
import requests, json, sys, os, time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:8080")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

def safe_request(method, path, **kw):
    try:
        r = requests.request(method, BASE_URL + path, timeout=30, **kw)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return 0, None, str(e)

def make_class(name, desiredCount):
    body = {"class": name, "vectorizer": "none",
            "shardingConfig": {"desiredCount": desiredCount}}
    return safe_request("POST", "/v1/schema", json=body)

def readback(name):
    s, b, t = safe_request("GET", f"/v1/schema/{name}")
    if s == 200 and b is not None:
        return s, (b.get("shardingConfig") or {}).get("desiredCount")
    return s, None

def cleanup(name):
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass

results = []
def unit(tag, val, expect_reject=True):
    name = f"BndShard_{tag}"
    cleanup(name)
    s, b, t = make_class(name, val)
    rb_s, rb = readback(name)
    print(f"[{tag}] desiredCount={val!r} -> create={s} readback={rb!r} raw={t[:200]}")
    results.append((tag, val, s, rb))
    cleanup(name)
    return s, rb

verdicts = []
# control group: valid value
cs, crb = unit("ctrl", 1)
if cs not in (200, 201):
    print(f"CONTROL FAILED: valid desiredCount=1 got {cs}"); print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

# attack units
unit("zero", 0)
unit("neg", -1)
unit("neg100", -100)
unit("float", 1.5)
unit("str", "3")
unit("huge", 2147483647)
unit("huge2", 10**12)

defect = False
for tag, val, s, rb in results:
    if tag == "ctrl": continue
    # IllegalSuccess: invalid value accepted with 2xx AND persisted (or runtime-poisoned)
    if s in (200, 201):
        if val in (0, -1, -100, 1.5, "3") or val == 2147483647 or val == 10**12:
            if rb is not None and rb == val:
                print(f"DEFECT[{tag}] Type1_IllegalSuccess: {val!r} accepted & persisted verbatim")
                defect = True
            elif rb is not None:
                print(f"NORM[{tag}] {val!r} accepted but normalized to {rb!r} (Type2 candidate)")
            else:
                print(f"DEFECT[{tag}] Type1_IllegalSuccess: {val!r} accepted (2xx) with absent/None readback")
                defect = True

print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
