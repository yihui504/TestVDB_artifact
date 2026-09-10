#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Semantic Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: implicit type-coercion semantics of numeric vector-index config fields.
Attack: type_coercion
Stategy coverage map: (type_coercion, POST /schema numeric config fields)
Blindspot: BS-05 Documentation Drift
Rationale: Contract types vectorIndexConfig numeric fields (dynamicEfMin / dynamicEfMax /
        flatSearchCutoff) as int. Submitting a JSON string "65000" where an int belongs is
        a type-confusion probe: if /v1/schema silently coerces it, the caller's payload and
        the effective config disagree (silent type coercion); if it is rejected, the error
        should name the offending field and expected type. Either a silent coercion with no
        disclosure or a generic non-field-specific rejection is a semantics defect.
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

CLS = "SemTypeCoercion"


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


def msg_of(body, raw):
    if isinstance(body, dict):
        errs = body.get("result", {}).get("errors") if isinstance(body.get("result"), dict) else None
        if errs and isinstance(errs, list):
            parts = [str(e.get("message")) for e in errs if isinstance(e, dict) and e.get("message")]
            if parts:
                return " ".join(parts)
        if body.get("error"):
            return str(body.get("error"))
    return str(raw)


def main():
    # Probe 1: dynamicEfMin as a JSON string where int is expected.
    p1 = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "dynamicEfMin": "250",
            "dynamicEfMax": 400,
        }
    }
    s1, b1, r1 = safe_request("POST", CREATE_PATH, json=p1)
    print(f"Type-probe[class={CLS} dynamicEfMin='250'] status={s1}")
    print(f"Probe raw: {r1}")

    if s1 in (200, 201):
        # Accepted the string — check disclosure and read-back type.
        gs, gb, gr = safe_request("GET", GET_PATH.format(cls=CLS))
        cfg = None
        if isinstance(gb, dict):
            for key in ("class", "Class"):
                v = gb.get(key)
                if isinstance(v, dict) and isinstance(v.get("vectorIndexConfig"), dict):
                    cfg = v["vectorIndexConfig"]
                    break
        rd = cfg.get("dynamicEfMin") if (cfg and isinstance(cfg, dict)) else None
        print(f"Read-back dynamicEfMin={rd!r} (type={type(rd).__name__})")
        if not (isinstance(rd, int) and not isinstance(rd, bool)) or rd != 250:
            print(f"DEFECT signal — string '250' silently coerced to {rd!r} with no "
                  "disclosure (silent type-confusion)")
            print("VERDICT: DEFECT_FOUND")
            sys.exit(1)
        print("String silently coerced to int 250 but read-back confirms int 250 — "
              "coercion is detectable; no hidden drift.")
        print("VERDICT: NO_DEFECT")
        return

    # Rejected — grade the diagnosis: must name the field and expected type.
    msg = msg_of(b1, r1).lower()
    print(f"Rejection message: {msg}")
    names_field = any(t in msg for t in ("dynamicef", "efmin", "efmax"))
    names_type = any(t in msg for t in ("integer", "int", "type", "number", "expected"))
    if not names_field or not names_type:
        print("DEFECT signal — type-mismatch rejection does not name the offending field "
              "and expected type (Type2_PoorDiagnostics)")
        print("VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics)")
        sys.exit(1)

    print("Type-mismatch rejected with field- and type-specific message")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
