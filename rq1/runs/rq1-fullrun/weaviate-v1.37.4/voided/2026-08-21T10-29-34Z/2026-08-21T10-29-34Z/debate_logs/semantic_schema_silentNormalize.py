#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Semantic Attack Script
Target: weaviate v1.37.4
Chunk: POST /schema
Attack: silent-normalization semantics of accepted vector-index config values.
Attack: behavioral_contract
Stategy coverage map: (behavioral_contract, POST /schema vectorIndexConfig normalization)
Blindspot: BS-02 Error Message Negligence / BS-05 Documentation Drift
Rationale: When /v1/schema ACCEPTS a submitted config value, a silent rewrite of that value
        (e.g. clamping a negative dynamicEfMin to a default, or coercing a float to an int)
        is only acceptable if it is DISCLOSED — either in the POST response body or through
        a GET /v1/schema read-back that differs observably from the submitted value. A
        value that is silently rewritten with no discovery path is a state-semantics defect:
        the caller believes their exact configuration is active when it is not.
        We probe two suspicious inputs: negative dynamicEfMin, and float-valued int fields.
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
GET_PATH = "/v1/schema/{cls}"
DROP_PATH = "/v1/schema/{cls}"

CLS = "SemSilentNormalize"


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


def get_vector_index_config(gs, body):
    if gs != 200:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("class", "Class"):
        v = body.get(key)
        if isinstance(v, dict):
            return v.get("vectorIndexConfig")
    cfg = body.get("vectorIndexConfig")
    return cfg if isinstance(cfg, dict) else None


def main():
    # submitted config with two normalization-suspicious values:
    #   - negative dynamicEfMin (-7) — a search-recall parameter cannot sensibly be negative
    #   - float flatSearchCutoff (12000.0) presented where an int is expected
    submitted = {
        "class": CLS,
        "vectorizer": "none",
        "vectorIndexType": "hnsw",
        "vectorIndexConfig": {
            "distance": "cosine",
            "dynamicEfMin": -7,
            "dynamicEfMax": 400,
            "flatSearchCutoff": 12000.0,
        }
    }

    ps, pbody, praw = safe_request("POST", CREATE_PATH, json=submitted)
    print(f"Create Status: {ps}")
    print(f"Create Raw: {praw}")
    if ps not in (200, 201):
        print("Rejected — values not accepted; silent-normalization path not reachable.")
        print("VERDICT: NO_DEFECT")
        return

    # Did the POST response disclose a rewritten value? weaviate create typically echoes
    # the class; scan the response for a vectorIndexConfig and compare.
    disclosed = None
    if isinstance(pbody, dict):
        cfg = pbody.get("vectorIndexConfig")
        if isinstance(pbody.get("class"), dict):
            cfg = pbody["class"].get("vectorIndexConfig")
        if cfg and isinstance(cfg, dict):
            disclosed = {
                "dynamicEfMin": cfg.get("dynamicEfMin"),
                "flatSearchCutoff": cfg.get("flatSearchCutoff"),
            }

    gs, gbody, graw = safe_request("GET", GET_PATH.format(cls=CLS))
    print(f"Describe Status: {gs}")
    print(f"Describe Raw: {graw}")
    rcfg = get_vector_index_config(gs, gbody)

    if rcfg is None:
        print("VERDICT: SCRIPT_ERROR — could not locate vectorIndexConfig in read-back")
        sys.exit(2)

    # Compare submitted vs read-back for the two suspicious fields.
    reads = {
        "dynamicEfMin": rcfg.get("dynamicEfMin"),
        "flatSearchCutoff": rcfg.get("flatSearchCutoff"),
    }
    print(f"Read-back: {reads}")
    print(f"POST-echo disclosure: {disclosed}")

    silent = []
    for field, submitted_val in (("dynamicEfMin", -7), ("flatSearchCutoff", 12000.0)):
        read_val = reads.get(field)
        if read_val is None:
            silent.append(f"{field}: MISSING after submission (submitted={submitted_val!r})")
        elif read_val != submitted_val:
            normalized = read_val
            # The rewrite itself is not the defect — the LACK of disclosure is.
            disclosed_any = (disclosed is not None
                             and field in disclosed
                             and disclosed[field] is not None
                             and disclosed[field] == read_val)
            if not disclosed_any:
                silent.append(
                    f"{field}: silently rewritten submitted={submitted_val!r} -> "
                    f"read-back={read_val!r} with NO disclosure in POST response")

    if silent:
        print("DEFECT signal — silent normalization without disclosure:")
        for s in silent:
            print("  " + s)
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    # pairing invariant sanity (assertion weaviate_inferred_hnsw_ef_pairing_001)
    mn = rcfg.get("dynamicEfMin")
    mx = rcfg.get("dynamicEfMax")
    if mn is not None and mx is not None and isinstance(mn, (int, float)) and isinstance(mx, (int, float)) and mn > mx:
        print(f"DEFECT signal — pairing violated on read-back: Min={mn} > Max={mx}")
        print("VERDICT: DEFECT_FOUND")
        sys.exit(1)

    print("No undisclosed silent normalization detected")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
