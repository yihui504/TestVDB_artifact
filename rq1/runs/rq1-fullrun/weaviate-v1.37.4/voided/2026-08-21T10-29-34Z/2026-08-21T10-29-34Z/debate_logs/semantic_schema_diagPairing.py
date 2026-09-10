#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Semantic Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: error-diagnosis quality of the dynamicEf pairing violation.
Constraint: assertion weaviate_inferred_hnsw_ef_pairing_001 (dynamicEfMin <= dynamicEfMax)
Attack: diagnosis_quality
Stategy coverage map: (diagnosis_quality, weaviate_inferred_hnsw_ef_pairing_001)
Blindspot: BS-02 Error Message Negligence — a rejected pairing must point at the real
        violating field pair, not emit a Kafkaesque/generic message.
Rationale: If POST /v1/schema rejects dynamicEfMin>dynamicEfMax with an HTTP error, the
        message must (a) name the violating field(s), (b) indicate the correct relationship
        (Min<=Max), (c) ideally be actionable. A rejection whose message names no field and
        gives no pairing hint is a Type2_PoorDiagnostics defect. If the server ACCEPTS the
        inverted pairing, there is no diagnosis to grade here (that illegal-accept case is
        the boundary agent's concern) — reported as NO_DEFECT with an observation.
"""

import os
import sys
import json
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
DROP_PATH = "/v1/schema/{cls}"

CLS = "SemDiagPairing"


def safe_request(method, endpoint, json=None, timeout=10):
    """(status, body, raw_text) wrapper — unified error handling."""
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


def json_lower(obj):
    try:
        return json.dumps(obj).lower()
    except Exception:
        return str(obj).lower()


def grade_error_quality(body, raw):
    """Type-2 diagnosis rubric (max 4): param-named + relationship + actionable + class.
    weaviate error envelope: {"result":{"errors":[{"message":..}]}} or {"error": ...}."""
    msg = ""
    if isinstance(body, dict):
        errs = body.get("result", {}).get("errors") if isinstance(body.get("result"), dict) else None
        if errs and isinstance(errs, list):
            for e in errs:
                if isinstance(e, dict) and e.get("message"):
                    msg += str(e.get("message"))
        if not msg and body.get("error"):
            msg += str(body.get("error"))
        if not msg:
            msg = json_lower(body)
    if not msg:
        msg = str(raw).lower()
    msg_l = msg.lower()
    score = 0
    for token in ("dynamicef", "dynamic_ef", "efmin", "efmax", "dynamic ef"):
        if token in msg_l:
            score += 1
            break
    for token in ("min", "max", "<= ", "<=", "greater", "smaller", "larger", "pairing"):
        if token in msg_l:
            score += 1
            break
    for token in ("must be", "expected", "should", "use", "set", "adjust", "valid"):
        if token in msg_l:
            score += 1
            break
    return score, msg


def main():
    payload = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "distance": "cosine",
            "dynamicEfMin": 300,
            "dynamicEfMax": 100
        }
    }
    status, body, raw = safe_request("POST", CREATE_PATH, json=payload)
    print(f"Create Status: {status}")
    print(f"Create Raw: {raw}")

    if status in (200, 201):
        print("Observation: inverted pairing was ACCEPTED (no diagnosis path; "
              "illegal-accept is the boundary agent's defect)")
        print("VERDICT: NO_DEFECT")
        return

    score, msg = grade_error_quality(body, raw)
    print(f"Error message: {msg}")
    print(f"Diagnosis score (0-4): {score}")

    if score <= 1:
        print("DEFECT signal — rejection message fails to name the violating pairing "
              "field/relationship (Type2_PoorDiagnostics)")
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        sys.exit(1)

    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
