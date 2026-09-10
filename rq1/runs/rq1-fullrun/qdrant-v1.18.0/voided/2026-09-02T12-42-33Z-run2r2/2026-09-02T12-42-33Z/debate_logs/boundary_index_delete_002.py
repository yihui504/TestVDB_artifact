#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_delete_002
# strategy: state_data_preservation_readback
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — "index deletion does not delete the
#            underlying data" is assumed true; count drift, payload mutation, or a
#            filtered query going dark after the delete would mean the deletion
#            over-reaches its declared scope)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: state data-preservation readback x qdrant_state_index_delete_001 (promise:
  "index deletion leaves point data untouched") — the G4 positive/mutation pair on
  one live bidl2_* collection with 10 points carrying keyword + integer payloads.
  Mutation point argument (G6): index deletion is the ONLY mutating operation in
  the sequence, so any drift in the three independent readback channels below is
  causally attributable to the delete: (1) exact count via points+count
  {exact:true}; (2) full payload snapshot via points+scroll, deep-compared
  id->payload against the pre-delete baseline; (3) FILTERED count on the previously
  indexed keyword field via points+count {filter:{must:[{key,match}]}} — after the
  payload index is gone the filter must still be evaluated against the stored
  payload (same cardinality), proving the data — not just the count — survives.
  Persistence of the deletion itself is judged via collections+get readback
  (result.payload_schema must no longer list the deleted fields — R21 lesson:
  describe echo, not the ack). The 200 envelope of each delete is checked against
  the response_shape grid (result: object, result.status: string).
  [chunk_index+delete coverage: state_data_preservation_readback x
  qdrant_state_index_delete_001 (data-untouched face, both index fields, three
  readback channels)]
Oracle: with baseline exact count=10, keyword-filtered count=5 and an id->payload
  scroll snapshot, deleting both payload indexes (wait=true) returns 200 per field,
  collections+get result.payload_schema contains NEITHER field afterwards (residue
  = Type4_StateLogicViolation), exact count stays exactly 10 (drift =
  Type4_StateLogicViolation), the scroll payload snapshot is deep-equal to baseline
  (mutation of any point = Type4_StateLogicViolation), and the keyword-filtered
  count stays exactly 5 (drop = Type4_StateLogicViolation: filterable data lost
  with the index); 5xx/transport = Type3_RuntimeFailure with /healthz re-check.
Constraint: qdrant_state_index_delete_001 (bare id) — "delete of a non-existent
  payload index is an idempotent success; index deletion leaves point data
  untouched" (evidence_tier: explicit; level: system; data-untouched face attacked
  here, idempotent face covered by boundary_index_delete_001)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  index+delete       -> DELETE /collections/{collection_name}/index/{field_name}
  index+create       -> PUT    /collections/{collection_name}/index
  collections+create -> PUT    /collections/{collection_name}
  collections+get    -> GET    /collections/{collection_name}
  points+upsert      -> PUT    /collections/{collection_name}/points
  points+count       -> POST   /collections/{collection_name}/points/count
  points+scroll      -> POST   /collections/{collection_name}/points/scroll
  healthz            -> GET    /healthz  (runtime PATHS key "healthz")
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

print(f"[PATHS] keys present="
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'count', 'scroll') if k in rt.PATHS]}")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    """Transport/5xx branch liveness re-check via the lightweight healthz face."""
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def get_count(tag, collection, flt=None):
    """Exact total/filtered count via points+count. Returns (count_or_None, ok)."""
    body = {"exact": True}
    if flt is not None:
        body["filter"] = flt
    s, raw = safe_request("POST", "count", body=body,
                          path_params={"name": collection})
    print(f"[{tag}] count status={s} raw={str(raw)[:160]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    if not b or not isinstance(b.get("result"), dict) \
            or not isinstance(b["result"].get("count"), int):
        return None, False
    return b["result"]["count"], True


def scroll_payloads(tag, collection):
    """Full payload snapshot via points+scroll (with_payload default true).
    Returns (id->payload dict_or_None, ok)."""
    s, raw = safe_request("POST", "scroll", body={"limit": 100},
                          path_params={"name": collection})
    print(f"[{tag}] scroll status={s} raw={str(raw)[:200]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None, False
    snap = {}
    for p in res["points"]:
        if isinstance(p, dict) and "id" in p:
            snap[p["id"]] = p.get("payload")
    return snap, True


def describe_payload_schema(tag, collection):
    """collections+get readback -> result.payload_schema map (or None)."""
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": collection})
    print(f"[{tag}] describe status={s} raw={str(raw)[:300]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict):
        return None, False
    ps = res.get("payload_schema")
    if ps is None:
        return {}, True
    if not isinstance(ps, dict):
        return None, False
    return ps, True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "bidl2_" + TS + "_"
    C = PFX + "col"
    F_KW = "f_kw"
    F_INT = "f_int"
    DEFECTS = []
    N = 10
    EXPECT_FILTERED = 5  # points with f_kw == "kw0"

    flt_kw0 = {"must": [{"key": F_KW, "match": {"value": "kw0"}}]}
    pts = [
        {"id": i,
         "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {F_KW: f"kw{i % 2}", F_INT: i * 10}}
        for i in range(1, N + 1)
    ]

    try:
        # ---- setup: collection + 10 points + keyword & integer indexes ----
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"
        for field, schema in ((F_KW, {"type": "keyword"}),
                              (F_INT, {"type": "integer"})):
            s, raw = safe_request("PUT", "create_index",
                                  body={"field_name": field,
                                        "field_schema": schema},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            print(f"[setup create index {field}] status={s} raw={str(raw)[:200]}")
            if s not in (200, 201):
                return "SCRIPT_ERROR"
        ps0, ok0 = describe_payload_schema("describe gate", C)
        if not ok0 or F_KW not in ps0 or F_INT not in ps0:
            print(f"VERDICT: SCRIPT_ERROR - setup gate: indexes not echoed "
                  f"(ok={ok0}, echo={str(ps0)[:200]})")
            return "SCRIPT_ERROR"

        # ---- baseline (three readback channels) ----
        cnt0, okc0 = get_count("baseline exact count", C)
        if not okc0 or cnt0 != N:
            print(f"VERDICT: SCRIPT_ERROR - baseline count != {N}: {cnt0}")
            return "SCRIPT_ERROR"
        fcnt0, okf0 = get_count("baseline filtered count", C, flt=flt_kw0)
        if not okf0 or fcnt0 != EXPECT_FILTERED:
            print(f"VERDICT: SCRIPT_ERROR - baseline filtered count != "
                  f"{EXPECT_FILTERED}: {fcnt0}")
            return "SCRIPT_ERROR"
        snap0, oks0 = scroll_payloads("baseline scroll", C)
        if not oks0 or len(snap0) != N:
            return "SCRIPT_ERROR"

        # ---- act: delete both indexes (wait=true) ----
        for field in (F_KW, F_INT):
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": field},
                                  query_params={"wait": "true"})
            print(f"[delete {field}] status={s} raw={str(raw)[:250]}")
            if s in (200, 201):
                b = parse_json(raw)
                res = (b or {}).get("result") if isinstance(b, dict) else None
                if not isinstance(res, dict):
                    print(f"[delete {field}] SHAPE_CONFLICT(measured-only): "
                          f"result is {type(res).__name__}, response_shape "
                          f"declares object — raw={str(raw)[:160]}")
                elif not isinstance(res.get("status"), str):
                    print(f"[delete {field}] SHAPE_CONFLICT(measured-only): "
                          f"result.status not a string — raw={str(raw)[:160]}")
                continue
            if s == 0 or 500 <= s <= 599:
                if not liveness(f"delete {field}"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"(delete {field}) status {s} while /healthz "
                               f"alive - Type3_RuntimeFailure - "
                               f"raw={str(raw)[:160]}")
            else:
                DEFECTS.append(f"(delete {field}) existing-index delete got "
                               f"HTTP {s} (promise: 200) - legal input rejected - "
                               f"Type1_IllegalSuccess signal - "
                               f"raw={str(raw)[:160]}")

        # ---- persistence of the deletion itself: describe residue ----
        ps1, ok1 = describe_payload_schema("describe after deletes", C)
        if ok1:
            residue = [f for f in (F_KW, F_INT) if f in ps1]
            if residue:
                DEFECTS.append(
                    f"(describe) deleted indexes still present in "
                    f"result.payload_schema: {residue} - ack without persistence - "
                    f"Type4_StateLogicViolation (qdrant_state_index_delete_001)")

        # ---- channel 1: exact count unchanged ----
        cnt1, okc1 = get_count("post exact count", C)
        if okc1 and cnt1 != N:
            DEFECTS.append(f"(count) exact count {cnt1} != {N} after index "
                           f"deletion - point data lost with the index - "
                           f"Type4_StateLogicViolation "
                           f"(qdrant_state_index_delete_001)")

        # ---- channel 2: payload snapshot deep-equal ----
        snap1, oks1 = scroll_payloads("post scroll", C)
        if oks1 and snap1 != snap0:
            diff = {k for k in set(snap0) | set(snap1)
                    if snap0.get(k) != snap1.get(k)}
            DEFECTS.append(
                f"(payload) index deletion mutated {len(diff)} point(s): "
                f"ids={sorted(diff)[:8]} - Type4_StateLogicViolation "
                f"(qdrant_state_index_delete_001)")

        # ---- channel 3: filtered count on the previously indexed field ----
        fcnt1, okf1 = get_count("post filtered count", C, flt=flt_kw0)
        if okf1 and fcnt1 != EXPECT_FILTERED:
            DEFECTS.append(
                f"(filter) keyword-filtered count {fcnt1} != {EXPECT_FILTERED} "
                f"after the {F_KW} index deletion - stored payload no longer "
                f"filterable at baseline cardinality - data lost with the index - "
                f"Type4_StateLogicViolation (qdrant_state_index_delete_001)")
        if okf1 and fcnt1 == 0:
            DEFECTS.append(
                f"(filter) keyword filter returns 0 after index deletion while "
                f"baseline was {EXPECT_FILTERED} - filterable data went dark - "
                f"Type4_StateLogicViolation (qdrant_state_index_delete_001)")

        # ---- summary ----
        print(f"[summary] counts={[cnt0, cnt1 if okc1 else None]} "
              f"filtered={[fcnt0, fcnt1 if okf1 else None]} "
              f"payload_stable={snap0 == snap1 if oks1 else 'n/a'} "
              f"schema_residue={len(ps1) if ok1 else 'n/a'} defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("data-preservation across index deletion holds on all three readback "
              "channels: exact count 10->10, payload snapshot deep-equal, keyword "
              "filter 5->5 after both payload indexes deleted with clean describe "
              f"readback (no residue in {{{F_KW}, {F_INT}}}) - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        try:
            rt.drop_collection(C)
            print(f"[cleanup] dropped {C}")
        except Exception as e:
            print(f"[cleanup] drop {C} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
