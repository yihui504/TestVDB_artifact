#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Boundary Attack Script R2
Target: milvus v2.6.17
Attack: Request-Timeout header semantic effectiveness (valid small / zero / negative / float)
Constraint: milvus_type_request_timeout_001
R1 covered extreme values only; R2 probes: does a PARSEABLE small value actually take effect
(timeout honored -> 408), and edge parse forms: "0" (valid int, zero seconds), "-1", "1.5", " 1 ".
"""
import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, create_collection, load_collection, drop_collection
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
API = BASE_URL.rstrip("/") + "/v2/vectordb/"
HEADERS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}

COL = "r2_timeout_sem_001"


def timed_req(path_key, payload, header_val, timeout=30):
    """Send with Request-Timeout header set to header_val (None = omit)."""
    h = dict(HEADERS)
    if header_val is not None:
        h["Request-Timeout"] = header_val
    url = API + path_key.replace("+", "/")
    t0 = time.time()
    try:
        r = requests.post(url, headers=h, data=json.dumps(payload), timeout=timeout)
        el = time.time() - t0
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, code_of(b), r.text[:200], el
    except Exception as e:
        return -1, None, "EXC:%s" % e, time.time() - t0


def main():
    drop_collection(COL)
    s, b, raw = create_collection(COL)
    print("setup create:", s, raw[:120])
    # load takes >1s usually -> good long op for timeout semantics
    cases = [
        ("0",     "valid int zero seconds: ctx immediately expired? expect fast 408 OR code!=0"),
        ("-1",    "negative int: parsed ok (strconv) -> deadline in past -> 408? or ignored"),
        ("1.5",   "float: unparseable by ParseInt -> silently ignored -> normal success"),
        (" 2",    "leading space: ParseInt rejects -> ignored -> normal success"),
        (None,    "control: no header -> normal success"),
    ]
    findings = []
    for val, note in cases:
        st, cd, raw2, el = timed_req("collections+load", {"collectionName": COL}, val)
        print("Request-Timeout=%r -> HTTP=%s code=%s elapsed=%.2fs | %s | %s"
              % (val, st, cd, el, note, raw2[:140]))
        # semantic checks
        if val in ("0", "-1"):
            if st == 200 and cd == 0:
                findings.append("Request-Timeout=%s parsed but NOT effective (load succeeded) - timeout semantics gap" % val)
        if val in ("1.5", " 2") and st == 408:
            findings.append("Request-Timeout=%r unparseable value unexpectedly caused 408" % val)

    # short timeout on a query path (loaded collection) for cross-endpoint comparison
    load_collection(COL)
    for val in ("1", None):
        st, cd, raw2, el = timed_req("entities+query",
            {"collectionName": COL, "filter": "id >= 0", "limit": 10}, val)
        print("query Request-Timeout=%r -> HTTP=%s code=%s elapsed=%.2fs | %s"
              % (val, st, cd, el, raw2[:120]))

    try:
        drop_collection(COL)
    except Exception:
        pass

    if findings:
        for f in findings:
            print("FINDING: " + f)
        print("VERDICT: DEFECT_FOUND (Type1_IllegalSuccess / Type2 semantics) — see FINDING lines")
    else:
        print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
