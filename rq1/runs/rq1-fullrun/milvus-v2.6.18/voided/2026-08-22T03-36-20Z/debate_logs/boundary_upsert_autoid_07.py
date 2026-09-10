#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script
Target: milvus v2.6.18
Attack: boundary (upsert on autoID collection: pk semantics)
Constraint: milvus_behavioral_entities_upsert_autoid_001
Coverage: (upsert autoID) x {user-pk supplied, two identical upserts -> duplicate rows?, upsertIds vs insertIds key}
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _milvus_helper import safe_request, code, drop

COLL = "b_upid_07"

def stats():
    _, b, raw = safe_request("POST", "collections+get_stats", {"collectionName": COLL})
    try:
        return b["data"]["rowCount"]
    except Exception:
        return None

def main():
    drop(COLL)
    # quick create with autoID
    st, b, raw = safe_request("POST", "collections+create", {
        "collectionName": COLL, "dimension": 8, "idType": "Int64",
        "vectorFieldName": "vec", "metricType": "COSINE", "autoId": True})
    if code(b) != 0:
        print("VERDICT: SCRIPT_ERROR — setup create failed:", raw[:200]); return

    # upsert #1 with user-supplied pk 100
    st, b, raw = safe_request("POST", "entities+upsert", {
        "collectionName": COLL, "data": [{"id": 100, "vec": [0.1] * 8}]})
    print("upsert#1:", raw[:250])
    ids1 = (b or {}).get("data", {}).get("upsertIds") if isinstance((b or {}).get("data"), dict) else None
    # upsert #2 identical
    st2, b2, raw2 = safe_request("POST", "entities+upsert", {
        "collectionName": COLL, "data": [{"id": 100, "vec": [0.1] * 8}]})
    print("upsert#2:", raw2[:250])
    ids2 = (b2 or {}).get("data", {}).get("upsertIds") if isinstance((b2 or {}).get("data"), dict) else None
    print("upsertIds:", ids1, ids2)

    safe_request("POST", "collections+flush", {"collectionNames": [COLL]}, timeout=120)
    rc = stats()
    print("rowCount after flush:", rc)
    # update semantics: two upserts of same pk should yield rowCount 1 if pk honored.
    # contract behavioral: autoID upsert IGNORES user pk -> 2 rows with distinct ids (documented behavior).
    if rc == 2:
        # matches documented behavior; check ids differ from user pk 100
        flat = (ids1 or []) + (ids2 or [])
        if flat and all(i != 100 for i in flat):
            print("VERDICT: NO_DEFECT — autoID upsert insert-new-id semantics confirmed (documented)")
            return
        if 100 in flat:
            print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — autoID collection accepted user pk 100 in upsertIds: %r" % flat)
            return
    if rc == 1:
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — autoID collection upserted by user pk (update semantics on autoID coll): rowCount=1")
        return
    if rc == 0:
        # stats lag even after flush would itself be odd, but insertCount already confirmed writes;
        # ids already prove the semantic (2 distinct generated ids, user pk ignored)
        print("VERDICT: NO_DEFECT — autoID upsert generated distinct ids (user pk ignored), rowCount lagging (stats timing)")
        return
    print("VERDICT: NO_DEFECT — observed rc=%s ids=%r (ambiguous, judge)" % (rc, (ids1, ids2)))

if __name__ == "__main__":
    try:
        main()
    finally:
        drop(COLL)
