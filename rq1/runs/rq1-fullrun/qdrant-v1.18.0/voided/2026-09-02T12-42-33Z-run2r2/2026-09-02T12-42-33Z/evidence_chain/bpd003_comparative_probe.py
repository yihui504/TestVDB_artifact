#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Comparative-forensics probe for boundary_payload_delete_003 (rule 5/6 obligation)
# Primary observation: {"points":[1],"keys":[]} -> 200 no-op ack (silently accepted vacuous body)
# Comparisons:
#   B: keys omitted (serde presence-required)      -> source expects 400 missing field
#   C: selector absent (DeletePayloadShadow try_from validator) -> source expects 400
#   D: same-family face payload+set with payload={} (vacuous body on sibling endpoint)
#   readback after each: payload state must be unchanged
import json
import os
import sys
import uuid

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("TESTVDB_DB_URL", "http://127.0.0.1:6333")
tag = uuid.uuid4().hex[:8]
coll = "bpd3probe" + tag
base_payloads = {1: {"city": "ams", "n": 1, "tag": "alpha"},
                 2: {"city": "par", "n": 2, "tag": "beta"}}
vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5]}

def req(method, path, body=None, params=None, timeout=30):
    r = requests.request(method, BASE + path, json=body,
                         headers={"Content-Type": "application/json"},
                         params=params, timeout=timeout)
    try:
        return r.status_code, r.text
    except Exception:
        return r.status_code, r.text

try:
    s, raw = req("PUT", f"/collections/{coll}",
                 {"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    print(f"setup create -> {s}")
    s, raw = req("PUT", f"/collections/{coll}/points",
                 {"points": [{"id": i, "vector": vecs[i], "payload": base_payloads[i]}
                             for i in (1, 2)]}, params={"wait": "true"}, timeout=60)
    print(f"setup upsert -> {s}")

    def scroll():
        s, raw = req("POST", f"/collections/{coll}/points/scroll",
                     {"limit": 100, "with_payload": True})
        body = json.loads(raw)
        pts = body.get("result", {}).get("points", [])
        return {p.get("id"): p.get("payload") for p in pts}

    print(f"baseline payloads: {scroll()}")

    cases = [
        ("A-repro rest: payload/delete {points:[1],keys:[]} (PRIMARY)",
         "POST", f"/collections/{coll}/points/payload/delete",
         {"points": [1], "keys": []}),
        ("B rest: payload/delete {points:[1]} keys omitted",
         "POST", f"/collections/{coll}/points/payload/delete",
         {"points": [1]}),
        ("C rest: payload/delete {keys:[city]} selector absent",
         "POST", f"/collections/{coll}/points/payload/delete",
         {"keys": ["city"]}),
        ("D rest same-family: payload/set {points:[1],payload:{}}",
         "POST", f"/collections/{coll}/points/payload",
         {"points": [1], "payload": {}}),
    ]
    for label, method, path, body in cases:
        s, raw = req(method, path, body, params={"wait": "true"}, timeout=60)
        print(f"\n[{label}] -> status={s}")
        print(f"raw: {raw[:300]}")

    print(f"\nfinal readback: {scroll()}")
    print(f"baseline was:  {base_payloads}")
finally:
    try:
        req("DELETE", f"/collections/{coll}", timeout=30)
    except Exception:
        pass
