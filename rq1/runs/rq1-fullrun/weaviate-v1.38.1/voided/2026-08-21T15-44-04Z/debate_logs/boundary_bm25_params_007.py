#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack — weaviate v1.38.1
Attack: invertedIndexConfig.bm25.b/k1 + cleanupIntervalSeconds 边界
对照组锚点：b=-0.5 / b=1.5 / k1=-1.2 / cleanup=-1 正确 422（校验存在）。
攻击：k1=0 合法边界；b=0；k1 未传时被 silent-drop（读回 bm25 只含 b）——
重点是 cleanupIntervalSeconds=0（违反 "must be > 0" 语义的边界）静默归一化 60、
cleanupIntervalSeconds=10^12 verbatim 持久化（int64 溢出/时间语义风险）。
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

def unit(tag, iic):
    name = f"BndBM_{tag}"
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    s, b, t = safe_request("POST", "/v1/schema", json={
        "class": name, "vectorizer": "none", "invertedIndexConfig": iic})
    c = bm = None
    gs, gb, _ = safe_request("GET", f"/v1/schema/{name}")
    if gs == 200 and gb:
        g = gb.get("invertedIndexConfig") or {}
        c, bm = g.get("cleanupIntervalSeconds"), g.get("bm25")
    print(f"[{tag}] iic={iic!r} -> create={s} persisted(cleanup={c!r},bm25={json.dumps(bm)})"
          + (f" err={t[:110]}" if s >= 400 else ""))
    try: safe_request("DELETE", f"/v1/schema/{name}")
    except Exception: pass
    return s, c, iic

units = [
    ("ctrl", {"cleanupIntervalSeconds": 60, "bm25": {"b": 0.75, "k1": 1.2}}),
    ("b_neg", {"bm25": {"b": -0.5, "k1": 1.2}}),          # expect 422 (anchor)
    ("b_gt1", {"bm25": {"b": 1.5, "k1": 1.2}}),           # expect 422 (anchor)
    ("k1_neg", {"bm25": {"b": 0.75, "k1": -1.2}}),        # expect 422 (anchor)
    ("cleanup_zero", {"cleanupIntervalSeconds": 0}),      # doc says must be > 0
    ("cleanup_huge", {"cleanupIntervalSeconds": 10**12}), # verbatim persist?
    ("cleanup_neg", {"cleanupIntervalSeconds": -1}),      # expect 422 (anchor)
]
res = [unit(*u) for u in units]

defect = False
for (tag, iic), (s, c, _) in zip(units, res):
    if tag in ("b_neg", "b_gt1", "k1_neg", "cleanup_neg") and s in (200, 201):
        print(f"ANCHOR FAILED: {tag} accepted"); defect = True
    if tag == "cleanup_huge" and s == 200 and c == 10**12:
        print("DEFECT[cleanup_huge] Type1_IllegalSuccess: 10^12 seconds persisted verbatim (~31000 years, no sanity cap)")
        defect = True
print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess)" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
