#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_001
# strategy: delete_consistency
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: delete_consistency (Strategy 2: post-DELETE consistency over the
  payload-index resource) x qdrant_state_index_delete_001 — both clauses of
  the constraint in one lifecycle on a single collection (12 points):
  (A) delete of a NON-EXISTENT payload index is an idempotent success (200)
  in two flavors — a field that never appears in any payload (f_ghost) and a
  field that carries payload data but was never indexed (f_noidx) — plus the
  third flavor, re-delete of a just-deleted index (f_kw/f_int after their
  real deletion);
  (B) deleting a REAL index does not delete the underlying data: persistence
  of the deletion is judged via describe readback (result.payload_schema
  absence after delete), while exact count and the full scroll payload
  snapshot must stay identical across baseline -> create -> delete -> re-delete.
  [chunk_index+delete coverage: delete_consistency x
  qdrant_state_index_delete_001 (clause A idempotence all 3 flavors + clause B
  data preservation + describe persistence readback)]
Oracle: DELETE /collections/{name}/index/{field} returns HTTP 200 for a
  never-indexed field, a data-bearing never-indexed field, an existing index
  and a just-deleted index alike (collection exists throughout); after the
  real-index deletions describe result.payload_schema contains NONE of the
  deleted fields; exact count stays exactly 12 and the scroll payload
  snapshot is deep-equal to baseline at every checkpoint. Any 4xx on an
  idempotent delete against an existing collection = Type1_IllegalSuccess;
  5xx or transport loss while /healthz alive = Type3_RuntimeFailure;
  payload_schema residue after delete, count drift or payload mutation =
  Type4_StateLogicViolation (qdrant_state_index_delete_001)
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

# path keys verified against sorted(rt.PATHS): delete_index/create_index/
# describe_collection/count/upsert_points/scroll/create_collection/
# drop_collection/healthz are all native qdrant runtime keys
print(f"[PATHS] index keys present="
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
    """Exact count via points+count (optionally filtered);
    returns (count_or_None, ok). Envelope: result.count integer."""
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
    """Full payload snapshot via points+scroll (with_payload explicit true).
    Returns (id->payload dict_or_None, ok)."""
    s, raw = safe_request("POST", "scroll",
                          body={"limit": 100, "with_payload": True},
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
    """describe_collection readback -> result.payload_schema map (or None).
    Returns (schema_map_or_None, ok)."""
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


def entry_data_type(entry):
    """payload_schema entries may be {'data_type': X, ...params} or a bare
    string; extract the declared data_type dynamically."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        dt = entry.get("data_type")
        if isinstance(dt, str):
            return dt
    return None


def check_delete_status(field, s, raw, DEFECTS):
    """One DELETE adjudicated: 200/201 pass; 4xx = legal idempotent delete
    rejected (Type1); 0/5xx = liveness-gated Type3."""
    if s in (200, 201):
        return True
    if s == 0 or 500 <= s <= 599:
        if liveness(f"delete {field}"):
            DEFECTS.append(
                f"(delete {field}) status {s} while /healthz alive - "
                f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
        return True  # already classified; do not abort the lifecycle
    DEFECTS.append(
        f"(delete {field}) idempotent index delete against an existing "
        f"collection rejected with HTTP {s} - Type1_IllegalSuccess - "
        f"raw={str(raw)[:160]} (qdrant_state_index_delete_001 clause A)")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd1_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    N = 12

    pts = [
        {"id": i,
         "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {
             "f_kw": f"kw{i % 3}",
             "f_int": i * 10,
             "f_noidx": f"plain{i}",
         }}
        for i in range(1, N + 1)
    ]

    try:
        # ---- setup: collection + points (wait=true for deterministic state) ----
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

        cnt0, ok0 = get_count("baseline count", C)
        if not ok0 or cnt0 != N:
            print(f"VERDICT: SCRIPT_ERROR - baseline count != {N}: {cnt0}")
            return "SCRIPT_ERROR"
        snap0, ok0s = scroll_payloads("baseline scroll", C)
        if not ok0s or len(snap0) != N:
            return "SCRIPT_ERROR"

        # ---- phase 1: clause A flavor 1+2 - delete NON-EXISTENT indexes ----
        for field in ("f_ghost", "f_noidx"):
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": field},
                                  query_params={"wait": "true"})
            print(f"[delete nonexistent {field}] status={s} raw={str(raw)[:200]}")
            check_delete_status(field, s, raw, DEFECTS)

        # data-bearing never-indexed field must still be fully present
        noidx_vals = {pid: (p or {}).get("f_noidx")
                      for pid, p in snap0.items()}
        snapA, okAs = scroll_payloads("scroll after nonexistent deletes", C)
        if okAs and {pid: (p or {}).get("f_noidx")
                     for pid, p in snapA.items()} != noidx_vals:
            DEFECTS.append(
                "(payload) deleting a non-existent index mutated f_noidx "
                "payload values - Type4_StateLogicViolation")

        # ---- phase 2: create real indexes (wait=true) + describe echo ----
        for field, schema in (("f_kw", {"type": "keyword"}),
                              ("f_int", {"type": "integer"})):
            s, raw = safe_request("PUT", "create_index",
                                  body={"field_name": field,
                                        "field_schema": schema},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            print(f"[create {field}] status={s} raw={str(raw)[:200]}")
            if s not in (200, 201):
                print(f"VERDICT: SCRIPT_ERROR - create {field}: {s} {str(raw)[:200]}")
                return "SCRIPT_ERROR"
        ps1, okps1 = describe_payload_schema("describe after create", C)
        if not okps1:
            print("VERDICT: SCRIPT_ERROR - describe after create not parseable")
            return "SCRIPT_ERROR"
        for field, want in (("f_kw", "keyword"), ("f_int", "integer")):
            got = entry_data_type(ps1.get(field))
            if ps1.get(field) is None or got != want:
                DEFECTS.append(
                    f"(describe) field {field} expected data_type={want} but "
                    f"payload_schema reports {got!r} - "
                    f"Type4_StateLogicViolation - echo={str(ps1.get(field))[:160]}")

        cnt1, ok1 = get_count("count after create", C)
        if ok1 and cnt1 != N:
            DEFECTS.append(
                f"(count) points count {cnt1} != {N} after index creation - "
                f"Type4_StateLogicViolation")

        # ---- phase 3: delete the REAL indexes (clause B mutation) ----
        for field in ("f_kw", "f_int"):
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": field},
                                  query_params={"wait": "true"})
            print(f"[delete real {field}] status={s} raw={str(raw)[:200]}")
            check_delete_status(field, s, raw, DEFECTS)

        ps2, okps2 = describe_payload_schema("describe after delete", C)
        if okps2:
            residue = [f for f in ("f_kw", "f_int") if f in ps2]
            if residue:
                DEFECTS.append(
                    f"(describe) deleted indexes still present in "
                    f"payload_schema: {residue} - Type4_StateLogicViolation "
                    f"- echo={str(ps2)[:200]}")

        # ---- phase 4: clause A flavor 3 - re-delete the just-deleted indexes ----
        for field in ("f_kw", "f_int"):
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": field},
                                  query_params={"wait": "true"})
            print(f"[re-delete {field}] status={s} raw={str(raw)[:200]}")
            check_delete_status(field, s, raw, DEFECTS)

        # ---- phase 5: final invariance - count + payload untouched ----
        cnt2, ok2 = get_count("count after delete", C)
        if ok2 and cnt2 != N:
            DEFECTS.append(
                f"(count) points count {cnt2} != {N} after index deletion - "
                f"Type4_StateLogicViolation - index deletion deleted data "
                f"(qdrant_state_index_delete_001 clause B)")
        snap2, ok2s = scroll_payloads("scroll after delete", C)
        if ok2s and snap2 != snap0:
            diff = {k for k in set(snap0) | set(snap2)
                    if snap0.get(k) != snap2.get(k)}
            DEFECTS.append(
                f"(payload) index deletion mutated {len(diff)} point "
                f"payload(s): ids={sorted(diff)[:8]} - "
                f"Type4_StateLogicViolation "
                f"(qdrant_state_index_delete_001 clause B)")
        # filtered reads on the previously-indexed fields still resolve
        fk, okf = get_count("filtered count f_kw after delete", C,
                            flt={"must": [{"key": "f_kw",
                                           "match": {"value": "kw1"}}]})
        if okf and fk != 4:  # ids 1,4,7,10 carry kw1
            DEFECTS.append(
                f"(filter) filtered count on previously-indexed f_kw returned "
                f"{fk}, expected 4 after index deletion - "
                f"Type4_StateLogicViolation - filter semantics must survive "
                f"index deletion")

        # ---- summary ----
        print(f"[summary] counts={[cnt0, cnt1 if ok1 else None, cnt2 if ok2 else None]} "
              f"payload_stable={snap0 == snap2 if ok2s else 'n/a'} "
              f"schema_after_delete={ps2 if okps2 else 'n/a'} defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("index deletion lifecycle complete: non-existent deletes (3 "
              "flavors) all 200; real-index deletes 200 with payload_schema "
              "absence on readback; count=12 and payload snapshot identical "
              "throughout - NO_DEFECT")
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
