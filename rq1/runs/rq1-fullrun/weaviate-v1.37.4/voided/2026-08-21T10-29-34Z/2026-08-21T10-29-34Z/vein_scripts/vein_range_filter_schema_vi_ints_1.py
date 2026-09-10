#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TestVDB Attack Vein - Range Filter Condition (vectorIndexConfig int validation surface)

Target: weaviate v1.37.4
Endpoint: POST /v1/schema (create class) -> vectorIndexConfig int params
Condition: range_filter - negative/zero values on int-declared params

Defect hypothesis: vectorIndexConfig int params have an INCONSISTENT validation
surface. Some are validated (maxConnections=-1 -> 422, efConstruction=-5 ->
422 via min-constraint), but others silently ACCEPT and PERSIST invalid
negative/zero values with HTTP 200, and the POST response echoes the invalid
value (disclosed, but accepted):
  - ef=-5 / ef=0                 (ef is the active HNSW search-time param; -1 is
                                  the documented default sentinel; -5/0 are not)
  - vectorCacheMaxObjects=-1     (default 1000000000000)
  - cleanupIntervalSeconds=-1    (default 300)
  - pq.centroids=-1              (default 256)
The asymmetry (422 for some ints, silent accept+persist for others on the same
config object) means the validation contract is not uniformly enforced.

Root finding chain: R1 found dynamicEfMin/Max + flatSearchCutoff silently coerce
wrong-typed string/bool to 0 (type_mismatch). R2 extends to numeric boundaries
on the OTHER int params of the same config object, checking which are validated
vs silently accepted.

Strategy: vein_range_filter
"""

import requests
import json
import re
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

PID = os.getpid()


def safe_request(method, path, json=None, timeout=15):
    """Resilient HTTP wrapper -> (status_code, body_or_None, raw_text)."""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    try:
        resp = requests.request(method=method, url=url, json=json,
                                headers=headers, timeout=timeout)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""


def get_nested(body, path):
    cur = body if isinstance(body, dict) else {}
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def cleanup():
    for cls in (f"VeinViEf{PID}", f"VeinViEfzero{PID}", f"VeinViVcm{PID}",
                f"VeinViCleanup{PID}", f"VeinViPqcentroids{PID}"):
        try:
            status, body, raw = safe_request("DELETE", f"/v1/schema/{cls}")
            if status not in (200, 204, 404):
                print(f"Cleanup warning: DELETE {cls} -> {status}")
        except Exception as e:
            print(f"Cleanup warning: {e}")


def main():
    # ---- Candidate params: invalid negative/zero accepted? ----
    cases = [
        ("ef",                 -5, ["vectorIndexConfig", "ef"]),
        ("efZero",              0, ["vectorIndexConfig", "ef"]),
        ("vectorCacheMaxObjects", -1, ["vectorIndexConfig", "vectorCacheMaxObjects"]),
        ("cleanupIntervalSeconds", -1, ["vectorIndexConfig", "cleanupIntervalSeconds"]),
        ("pq.centroids",       -1, ["vectorIndexConfig", "pq", "centroids"]),
    ]
    accepted_invalid = []
    for name, val, vpath in cases:
        safe = re.sub(r"[^A-Za-z0-9]", "", name)
        cls = f"VeinVi{safe.capitalize()}{PID}"
        payload = {"class": cls, "vectorizer": "none"}
        # nest the param into vectorIndexConfig (pq needs its own sub-object)
        if vpath[1] == "pq":
            payload["vectorIndexConfig"] = {"pq": {vpath[2]: val}}
        else:
            payload["vectorIndexConfig"] = {vpath[1]: val}
        st, body, raw = safe_request("POST", "/v1/schema", json=payload)
        gst, gbody, graw = safe_request("GET", f"/v1/schema/{cls}")
        readback = get_nested(gbody, vpath)
        print(f"candidate {name}={val}: POST={st} readback={readback}")
        if st in (200, 201) and readback == val:
            accepted_invalid.append((name, val, readback))
        safe_request("DELETE", f"/v1/schema/{cls}")

    # ---- Controls: same config object, validated params ----
    ctrl_results = {}
    for name, val, vpath in [
        ("maxConnections", -1, ["vectorIndexConfig", "maxConnections"]),
        ("efConstruction", -5, ["vectorIndexConfig", "efConstruction"]),
    ]:
        cls = f"VeinViCtrl{name.capitalize()}{PID}"
        payload = {"class": cls, "vectorizer": "none",
                   "vectorIndexConfig": {vpath[1]: val}}
        st, body, raw = safe_request("POST", "/v1/schema", json=payload)
        ctrl_results[name] = st
        print(f"control {name}={val}: POST={st} {raw[:120]}")
        if st in (200, 201):
            safe_request("DELETE", f"/v1/schema/{cls}")

    # ---- Judgment ----
    controls_reject = all(s in (400, 422) for s in ctrl_results.values())
    if accepted_invalid and controls_reject:
        print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess): "
              f"vectorIndexConfig int params inconsistently validated: "
              f"{accepted_invalid} accepted AND persisted (HTTP 200, response "
              f"echoes value, GET read-back confirms) while controls "
              f"maxConnections={ctrl_results.get('maxConnections')}, "
              f"efConstruction={ctrl_results.get('efConstruction')} are "
              f"rejected on the same config object. ef=-5/0 is especially "
              f"notable: ef is the active HNSW search-time param (documented "
              f"default sentinel is -1); -5/0 are invalid values persisted "
              f"silently.")
        sys.exit(1)
    elif accepted_invalid:
        print(f"VERDICT: NO_DEFECT: invalid values accepted ({accepted_invalid}) "
              f"but controls also accepted ({ctrl_results}) -> uniform behavior, "
              f"no validation asymmetry.")
        sys.exit(0)
    else:
        print(f"VERDICT: NO_DEFECT: all candidates rejected or not persisted "
              f"({ctrl_results}).")
        sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
