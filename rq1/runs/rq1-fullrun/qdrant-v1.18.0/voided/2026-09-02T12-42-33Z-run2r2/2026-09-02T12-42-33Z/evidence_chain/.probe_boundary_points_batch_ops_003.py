#!/usr/bin/env python3
# -*- coding utf-8 -*-
# evidence-builder comparative probe for boundary_points_batch_ops_003 (v2: fixed readback)
# readback uses GET /collections/{c}/points/1 (404 when absent) like the original script
import json
import os
import sys
import uuid

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.environ.get("TESTVDB_DB_URL", "http://127.0.0.1:6333")
DIM = 4
V = [0.1, 0.2, 0.3, 0.4]


def req(method, path, **kw):
    r = requests.request(method, BASE + path, timeout=30, **kw)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body


def seed(coll):
    s, b = req("PUT", f"/collections/{coll}/points",
               json={"points": [{"id": 1, "vector": V, "payload": {"seed": 1}}]},
               params={"wait": "true"})
    return s


def point1_present(coll):
    # single-point GET: 200 = exists, 404 = gone
    s, _ = req("GET", f"/collections/{coll}/points/1")
    return s


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "eb3cmp" + tag
    s, b = req("PUT", f"/collections/{coll}",
               json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"setup create {coll} -> {s}")
    try:
        upsert_body = {"points": [{"id": 2, "vector": V, "payload": {"k": 1}}]}

        # P1 exact F7 replay: upsert key first
        s, b = req("POST", f"/collections/{coll}/points/batch",
                   json={"operations": [{"upsert": upsert_body, "delete": {"points": [1]}}]},
                   params={"wait": "true"})
        gs = point1_present(coll)
        print(f"P1 F7 replay (upsert-first two-key op) -> batch={s} body={json.dumps(b)}")
        print(f"P1 point1 GET -> {gs} ({'present' if gs == 200 else 'DELETED'})")

        # P2 reversed key order: delete key first in the JSON object
        seed(coll)
        s, b = req("POST", f"/collections/{coll}/points/batch",
                   json={"operations": [{"delete": {"points": [1]}, "upsert": upsert_body}]},
                   params={"wait": "true"})
        gs = point1_present(coll)
        print(f"P2 reversed key order (delete-first two-key op) -> batch={s} body={json.dumps(b)}")
        print(f"P2 point1 GET -> {gs} ({'present' if gs == 200 else 'DELETED'})")

        # P3 legal decomposition control: two separate single-key ops
        seed(coll)
        s, b = req("POST", f"/collections/{coll}/points/batch",
                   json={"operations": [{"upsert": upsert_body}, {"delete": {"points": [1]}}]},
                   params={"wait": "true"})
        gs = point1_present(coll)
        n = len(b.get("result", [])) if isinstance(b, dict) else None
        print(f"P3 legal two-op decomposition -> batch={s} result_entries={n} body={json.dumps(b)[:220]}")
        print(f"P3 point1 GET -> {gs} ({'present' if gs == 200 else 'DELETED'})")
    finally:
        s, _ = req("DELETE", f"/collections/{coll}")
        print(f"cleanup delete {coll} -> {s}")


if __name__ == "__main__":
    main()
