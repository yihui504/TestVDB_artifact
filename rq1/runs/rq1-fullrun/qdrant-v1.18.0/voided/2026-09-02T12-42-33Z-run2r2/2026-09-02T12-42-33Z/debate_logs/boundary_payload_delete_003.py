#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_payload_delete_003
# strategy: strategy1 boundary-value (keys-presence boundary + selector-presence boundary)
# endpoint: payload+delete
# constraint_ids: qdrant_state_payload_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/delete-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — assuming a destructive selective
#            delete requires a non-vacuous keys list and an explicit point
#            selector; the empty/omitted boundaries probe what is silently
#            accepted and what it silently does)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value (presence boundaries) x
  qdrant_state_payload_delete_001 — the NEGATIVE direction of the G4 pair. The
  endpoint spec types `keys` as array[string] with required=true (the operation
  is literally defined by its keys list), while the selector branches
  (points / filter.* / shard_key.*) form the request_required_paths anyOf. Three
  boundary probes on one live bpdel3_* collection with 2 payload-bearing points:
  (a) {"points":[1],"keys":[]} — the EMPTY keys list (zero listed keys: a
      vacuous destructive request);
  (b) {"points":[1]} — keys OMITTED entirely (violates required=true);
  (c) {"keys":["city"]} — selector ABSENT (points nor filter nor shard_key
      absent: which points' "city" key would a selector-less delete remove?).
  Adjudication sub-typed by readback (never by status alone): 4xx = clean reject
  (diagnostics scanned for Type-2); 200 with all payloads deep-equal baseline
  after grace polls = Type1_IllegalSuccess (no-op ack on a vacuous/selector-less
  destructive request the spec does not license); 200 with ANY payload key gone
  = Type4 (for (c): unbounded bulk key-wipe from a selector-less request).
  G3 note: threat-model "filter=null treated as no-filter" is by-design for READ
  endpoints (query/search) where a missing filter is harmless; here the
  expectation keys on the spec-derived requiredness of `keys` and the
  request_required_paths anyOf of the DESTRUCTIVE delete face, where "no keys"
  and "no target" have no licensed meaning.
  [chunk_payload+delete coverage: state readback x qdrant_state_payload_delete_001,
  keys/selector presence boundary (this script)]
Oracle: each of the three boundary bodies — {"points":[1],"keys":[]},
  {"points":[1]} and {"keys":["city"]} — returns a 4xx reject (keys required per
  endpoint spec; selector anyOf per request_required_paths); any 200 is
  adjudicated by scroll readback after grace polls — payloads still deep-equal
  baseline = Type1_IllegalSuccess (no-op ack on vacuous/selector-less delete),
  any payload key gone = Type4_StateLogicViolation (unbounded key-wipe);
  5xx = Type3_RuntimeFailure with /healthz re-check; a 4xx whose error body
  names none of keys/points/filter = Type2_PoorDiagnostics (constraint
  qdrant_state_payload_delete_001).
Constraint: qdrant_state_payload_delete_001 (bare id) — "delete removes only the
  listed keys; all other payload keys stay untouched" (evidence_tier: explicit;
  level: system; the boundary attacks the precondition of "the listed keys" and
  "the targeted points" — with zero listed keys or no declared target the
  operation must not silently succeed)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  payload+delete      -> POST /collections/{collection_name}/points/payload/delete
  points+upsert       -> PUT  /collections/{collection_name}/points
  points+scroll       -> POST /collections/{collection_name}/points/scroll
  collections+create  -> PUT  /collections/{collection_name}
  collections+delete  -> DELETE /collections/{collection_name}
  healthz             -> GET  /healthz
  (wait is a query parameter on the point-mutation faces — passed via params=)
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- X1 bootstrap: three-layer fallback (env -> upward walk -> contract target) ---
BASE_URL = os.environ.get("TESTVDB_DB_URL")
TARGET = os.environ.get("TESTVDB_TARGET", "")
if not TARGET:
    _root = Path(__file__).resolve()
    for _p in (_root, *list(_root.parents)):
        _f = _p / "structured_contract.json"
        if _f.exists():
            try:
                _c = json.loads(_f.read_text(encoding="utf-8"))
                TARGET = _c.get("target", "") or TARGET
            except Exception:
                pass
            break
if not BASE_URL or TARGET != "qdrant":
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL/TESTVDB_TARGET missing (bootstrap fallback failed)")
    sys.exit(2)


def safe_request(method, endpoint, json=None, timeout=30, params=None):
    """
    Safe HTTP request wrapper with unified error handling.
    Returns: (status_code, body, raw_text); transport failure -> (-1, err, err).
    params= forwards query parameters exactly (wait/timeout live in the query
    string on qdrant point-mutation faces).
    """
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.request(
            method=method, url=url, json=json, headers=headers,
            timeout=timeout, params=params,
        )
        status_code = response.status_code
        raw_text = response.text
        try:
            body = response.json()
        except Exception:
            body = raw_text
        return status_code, body, raw_text
    except Exception as e:
        return -1, str(e), str(e)


def transport_dead():
    """Liveness re-check on the lightweight healthz face (transport branch)."""
    hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
    print(f"transport failure (healthz status={hs}: {str(hraw)[:200]})")
    print("VERDICT: SCRIPT_ERROR — transport failure, no defect conclusion")
    return


def scroll_payloads(coll):
    """id -> payload dict from points+scroll (with_payload).
    Returns (payloads, chan_err); None payloads means channel unusable."""
    s, body, raw = safe_request(
        "POST", f"/collections/{coll}/points/scroll",
        json={"limit": 100, "with_payload": True}, timeout=30)
    if s != 200 or not isinstance(body, dict):
        return None, (s, raw)
    res = body.get("result")
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None, (s, raw)
    return {p.get("id"): p.get("payload") for p in pts if isinstance(p, dict)}, (s, raw)


def main():
    tag = uuid.uuid4().hex[:8]
    coll = "bpdel3" + tag
    base_payloads = {
        1: {"city": "ams", "n": 1, "tag": "alpha"},
        2: {"city": "par", "n": 2, "tag": "beta"},
    }
    vecs = {1: [0.1, 0.2, 0.3, 0.4], 2: [0.2, 0.3, 0.4, 0.5]}

    # Arrange: data-bearing collection (own data, own cleanup)
    s, _, raw = safe_request("PUT", f"/collections/{coll}",
                             json={"vectors": {"size": 4, "distance": "Cosine"}}, timeout=60)
    if s not in (200, 201):
        print(f"setup create failed status={s}: {raw[:300]}")
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return
    s, _, raw = safe_request(
        "PUT", f"/collections/{coll}/points",
        json={"points": [{"id": i, "vector": vecs[i], "payload": base_payloads[i]}
                         for i in (1, 2)]},
        params={"wait": "true"}, timeout=60)
    if s not in (200, 201):
        print(f"setup upsert failed status={s}: {raw[:300]}")
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass
        print("VERDICT: SCRIPT_ERROR — setup failure, no defect conclusion")
        return

    try:
        # baseline readback (poll until both payloads visible)
        pls, cerr = scroll_payloads(coll)
        for _ in range(6):
            if pls is not None and pls.get(1) == base_payloads[1] \
                    and pls.get(2) == base_payloads[2]:
                break
            time.sleep(0.5)
            pls, cerr = scroll_payloads(coll)
        if pls is None or pls.get(1) != base_payloads[1] or pls.get(2) != base_payloads[2]:
            print(f"baseline readback unusable: {str(cerr)[:300]}")
            print("VERDICT: SCRIPT_ERROR — baseline readback failure, no defect conclusion")
            return
        print("baseline: both payloads visible via scroll")

        # (label, body) — the three presence boundaries
        cases = [
            ("keys=[] (empty keys list, spec: keys required)",
             {"points": [1], "keys": []}),
            ("keys omitted (spec: keys required=true)",
             {"points": [1]}),
            ("selector absent (spec anyOf: points|filter|shard_key)",
             {"keys": ["city"]}),
        ]
        for label, body in cases:
            s, _, raw = safe_request(
                "POST", f"/collections/{coll}/points/payload/delete",
                json=body, params={"wait": "true"}, timeout=60)
            print(f"\ncase {label} -> status={s}")
            print(f"raw: {raw[:500]}")

            if s <= 0:
                transport_dead()
                return
            if 500 <= s <= 599:
                hs, _, hraw = safe_request("GET", "/healthz", timeout=10)
                print(f"5xx on boundary body (healthz status={hs}: {hraw[:200]})")
                print(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — boundary case "
                      f"{label} triggered server error {s}")
                return
            if 200 <= s <= 299:
                # accepted a vacuous/selector-less destructive request — sub-judge
                pls2, cerr2 = scroll_payloads(coll)
                changed = pls2 is not None and any(
                    pls2.get(i) != base_payloads[i] for i in (1, 2))
                for _ in range(4):  # async grace
                    if changed:
                        break
                    time.sleep(0.5)
                    pls2, _ = scroll_payloads(coll)
                    if pls2 is not None:
                        changed = any(pls2.get(i) != base_payloads[i] for i in (1, 2))
                if pls2 is None:
                    print(f"VERDICT: SCRIPT_ERROR — readback channel failure: "
                          f"{str(cerr2)[:300]}")
                    return
                if changed:
                    print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — case "
                          f"{label} was 200-accepted AND changed payload state: "
                          f"{pls2} (baseline {base_payloads})")
                else:
                    print(f"VERDICT: DEFECT_FOUND (Type1_IllegalSuccess) — case "
                          f"{label} 200-accepted although the spec licenses no "
                          f"such request (keys required / selector anyOf); "
                          f"payloads intact (no-op ack)")
                return
            if s in (400, 404, 422):
                low = raw.lower()
                if "key" not in low and "point" not in low and "filter" not in low:
                    print(f"VERDICT: DEFECT_FOUND (Type2_PoorDiagnostics) — case "
                          f"{label} rejected with {s} but the error names no "
                          f"keys/points/filter parameter: {raw[:300]}")
                    return
                print(f"OK: case {label} cleanly rejected with {s} naming a parameter")
                continue
            print(f"NOTE: case {label} returned {s} (unexpected status family; raw "
                  f"above for judge)")
            print("VERDICT: NO_DEFECT")
            return

        # final readback: rejected boundary bodies must have left state untouched
        pls3, cerr3 = scroll_payloads(coll)
        if pls3 is None:
            print(f"VERDICT: SCRIPT_ERROR — final readback failure: {str(cerr3)[:300]}")
            return
        for i in (1, 2):
            if pls3.get(i) != base_payloads[i]:
                print(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — payload of "
                      f"point {i} changed although every boundary body was rejected: "
                      f"{pls3.get(i)} != {base_payloads[i]}")
                return
        print("all three presence-boundary bodies rejected; payloads deep-equal baseline")
        print("VERDICT: NO_DEFECT")
    finally:
        try:
            safe_request("DELETE", f"/collections/{coll}", timeout=30)
        except Exception:
            pass  # cleanup failures are non-fatal


if __name__ == "__main__":
    main()
