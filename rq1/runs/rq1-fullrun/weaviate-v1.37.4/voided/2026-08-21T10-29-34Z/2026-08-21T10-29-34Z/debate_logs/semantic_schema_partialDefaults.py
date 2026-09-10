#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Semantic Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: partial vectorIndexConfig-submission default-interaction semantics.
Constraint: contract POST /schema params dynamicEfMin(default 100) / dynamicEfMax(500) /
        flatSearchCutoff(40000), + assertion weaviate_inferred_hnsw_ef_pairing_001.
Attack: behavioral_contract
Stategy coverage map: (behavioral_contract, POST /schema flatSearchCutoff partial defaults)
Blindspot: BS-05 Documentation Drift — partial-submission must compose with documented
        field defaults into a coherent, valid index config.
Rationale: When a caller submits ONLY flatSearchCutoff (leaving dynamicEfMin/Max unset),
        /v1/schema should compose the provided field with the documented defaults
        (Min=100, Max=500) into a coherent config: the read-back must surface the defaulted
        dynamicEf values (not silently drop them to 0/omitted) AND preserve the pairing
        invariant Min<=Max. A read-back that omits or zeroes the defaulted EF fields, or a
        combo that violates Min<=Max, is a default-interaction semantics defect.
"""

import os
import sys
import requests

# Windows encoding compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

CREATE_PATH = "/v1/schema"
GET_PATH = "/v1/schema/{cls}"
DROP_PATH = "/v1/schema/{cls}"

CLS = "SemPartialDefaults"

# documented defaults from contract POST /schema parameter plane
DEF_MIN = 100
DEF_MAX = 500
SUBMIT_CUTOFF = 65000


def safe_request(method, endpoint, json=None, timeout=10):
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.request(method=method, url=url, json=json,
                                headers=headers, timeout=timeout)
        code = resp.status_code
        raw = resp.text
        try:
            body = resp.json()
        except Exception:
            body = raw
        return code, body, raw
    except Exception as e:
        return -1, str(e), str(e)


def cleanup():
    try:
        safe_request("DELETE", DROP_PATH.format(cls=CLS))
    except Exception as e:
        print(f"Cleanup warning: {e}")


def main():
    # Arrange: submit ONLY flatSearchCutoff — dynamicEfMin/Max left to defaults.
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "flatSearchCutoff": SUBMIT_CUTOFF,
        }
    }
    status, body, raw = safe_request("POST", CREATE_PATH, json=payload)
    print(f"Create Status: {status}")
    print(f"Create Raw: {raw}")
    if status not in (200, 201):
        print("VERDICT: SCRIPT_ERROR — create_schema failed: " + str(raw)[:200])
        sys.exit(2)

    # Act: read back the composed config.
    gs, gbody, graw = safe_request("GET", GET_PATH.format(cls=CLS))
    print(f"Describe Status: {gs}")
    print(f"Describe Raw: {graw}")

    cfg = None
    if isinstance(gbody, dict):
        for key in ("class", "Class"):
            v = gbody.get(key)
            if isinstance(v, dict) and isinstance(v.get("vectorIndexConfig"), dict):
                cfg = v["vectorIndexConfig"]
                break
        if cfg is None and isinstance(gbody.get("vectorIndexConfig"), dict):
            cfg = gbody["vectorIndexConfig"]
    if cfg is None:
        print("VERDICT: SCRIPT_ERROR — could not locate vectorIndexConfig in read-back")
        sys.exit(2)

    mn = cfg.get("dynamicEfMin")
    mx = cfg.get("dynamicEfMax")
    cutoff = cfg.get("flatSearchCutoff")
    print(f"Composed config — dynamicEfMin={mn}, dynamicEfMax={mx}, "
          f"flatSearchCutoff={cutoff}")

    defects = []

    # The defaulted EF fields must not be silently dropped to 0 / absent.
    intlike = lambda x: x is not None and isinstance(x, (int, float))
    if not intlike(mn):
        defects.append(f"dynamicEfMin default not materialized in read-back (got {mn!r})")
    elif mn != DEF_MIN:
        defects.append(f"dynamicEfMin default composed as {mn} (expected {DEF_MIN})")

    if not intlike(mx):
        defects.append(f"dynamicEfMax default not materialized in read-back (got {mx!r})")
    elif mx != DEF_MAX:
        defects.append(f"dynamicEfMax default composed as {mx} (expected {DEF_MAX})")

    # The submitted field must be honored.
    if not intlike(cutoff) or cutoff != SUBMIT_CUTOFF:
        defects.append(f"flatSearchCutoff not preserved: submitted {SUBMIT_CUTOFF} -> {cutoff!r}")

    # Pairing invariant (assertion weaviate_inferred_hnsw_ef_pairing_001)
    if intlike(mn) and intlike(mx) and mn > mx:
        defects.append(f"pairing violated: Min={mn} > Max={mx}")

    if defects:
        print("DEFECT signal — partial-submission default interaction inconsistent:")
        for d in defects:
            print("  " + d)
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    print("Partial submission composed with documented defaults coherently "
          f"(Min={mn}, Max={mx}, cutoff={cutoff})")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
