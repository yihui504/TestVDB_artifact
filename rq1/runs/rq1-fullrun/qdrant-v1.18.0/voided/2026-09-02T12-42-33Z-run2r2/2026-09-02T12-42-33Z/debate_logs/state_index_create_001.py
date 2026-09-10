#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_create_001
# strategy: index_state
# endpoint: index+create
# constraint_ids: qdrant_type_index_create_001, qdrant_inv_index_toggle_preserves_data_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: index_state (Strategy 1/6: CRUD-then-COUNT over the payload-index
  resource) x qdrant_type_index_create_001 (positive side: the FULL
  PayloadSchemaType domain keyword/integer/float/geo/text/bool/datetime/uuid
  plus the text tokenizer enum) + state invariant
  qdrant_inv_index_toggle_preserves_data_001 (creating and deleting a payload
  index changes ONLY payload_schema; stored points/payload/count remain
  unchanged). One collection, 8 payload fields (one per enum member), 12
  points. Lifecycle: (1) baseline count=12 + scroll payload snapshot;
  (2) PUT /collections/{name}/index (index+create, wait=true) for each of
  the 8 fields, valid schema objects per contract
  request_required_paths=[field_name, field_schema.type] -> each must be
  HTTP 200; (3) describe readback: result.payload_schema must contain all 8
  fields with data_type == the enum member created (persistence judged via
  describe echo, not the ack alone); (4) count still 12 AND payloads
  deep-equal the baseline snapshot (invariant: index build must not alter
  data); (5) delete all 8 indexes (wait=true) -> 200 each; describe shows
  no residue; count/payload STILL unchanged (both toggle directions).
  [chunk_index+create coverage: index_state x qdrant_type_index_create_001
  (all-enum positive + describe persistence) x
  qdrant_inv_index_toggle_preserves_data_001 (both directions)]
Oracle: each of the 8 valid schema creates returns HTTP 200 and the field
  appears in describe result.payload_schema with matching data_type; count
  stays exactly 12 and the scroll payload snapshot is byte-identical before,
  between and after the full index toggle; after deleting all 8 indexes no
  field remains in payload_schema. Any 4xx on a valid enum create =
  Type1_IllegalSuccess (legal input rejected); 5xx with /healthz alive =
  Type3_RuntimeFailure; missing/wrong data_type echo, schema residue after
  delete, count drift or payload mutation = Type4_StateLogicViolation
  (qdrant_type_index_create_001, qdrant_inv_index_toggle_preserves_data_001)
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

# path keys verified against sorted(rt.PATHS): create_index/delete_index/
# describe_collection/count/upsert_points/scroll/create_collection/
# drop_collection/healthz are all native qdrant runtime keys
print(f"[PATHS] index keys present="
      f"{[k for k in ('create_index', 'delete_index', 'describe_collection', 'count', 'scroll') if k in rt.PATHS]}")


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


def get_count(tag, collection):
    """Exact total count via points+count; returns (count_or_None, ok)."""
    s, raw = safe_request("POST", "count", body={"exact": True},
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


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidx1_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    N = 12

    # one field per PayloadSchemaType enum member; text carries a tokenizer
    # from the documented enum (word)
    FIELDS = [
        ("f_kw", {"type": "keyword"}),
        ("f_int", {"type": "integer"}),
        ("f_flt", {"type": "float"}),
        ("f_geo", {"type": "geo"}),
        ("f_txt", {"type": "text", "tokenizer": "word"}),
        ("f_bool", {"type": "bool"}),
        ("f_dt", {"type": "datetime"}),
        ("f_uid", {"type": "uuid"}),
    ]

    def uuid_for(i):
        return f"550e8400-e29b-41d4-a716-{i:012d}"

    pts = [
        {"id": i,
         "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {
             "f_kw": f"kw{i % 4}",
             "f_int": i * 10,
             "f_flt": 0.5 + i / 100.0,
             "f_geo": {"lon": 13.4, "lat": 52.5 + i / 100.0},
             "f_txt": f"alpha beta gamma {i}",
             "f_bool": (i % 2 == 0),
             "f_dt": f"2026-01-{(i % 28) + 1:02d}T03:04:05Z",
             "f_uid": uuid_for(i),
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

        # ---- phase 1: create all 8 valid indexes (wait=true) ----
        for field, schema in FIELDS:
            s, raw = safe_request("PUT", "create_index",
                                  body={"field_name": field,
                                        "field_schema": schema},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            print(f"[create {field} schema={schema}] status={s} "
                  f"raw={str(raw)[:200]}")
            if s in (200, 201):
                continue
            if s == 0:
                if liveness(f"create {field}"):
                    DEFECTS.append(
                        f"(create {field} schema={schema}) transport loss "
                        f"(status 0) while /healthz alive - "
                        f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
                else:
                    return "SCRIPT_ERROR"
            elif 500 <= s <= 599:
                if liveness(f"create {field}"):
                    DEFECTS.append(
                        f"(create {field} schema={schema}) HTTP {s} on a valid "
                        f"enum member while /healthz alive - "
                        f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
                else:
                    return "SCRIPT_ERROR"
            else:
                DEFECTS.append(
                    f"(create {field} schema={schema}) legal enum member "
                    f"rejected with HTTP {s} - Type1_IllegalSuccess - "
                    f"raw={str(raw)[:160]} (qdrant_type_index_create_001)")

        # ---- phase 2: describe persistence echo (all 8, matching types) ----
        ps, okps = describe_payload_schema("describe after create", C)
        if not okps:
            print("NOTE: describe readback after create not parseable; "
                  "persistence echo unadjudicable")
        else:
            for field, schema in FIELDS:
                want = schema["type"]
                got = entry_data_type(ps.get(field))
                if ps.get(field) is None:
                    DEFECTS.append(
                        f"(describe) field {field} created with 200 but absent "
                        f"from result.payload_schema (echo={ps}) - "
                        f"Type4_StateLogicViolation - ack without persistence")
                elif got != want:
                    DEFECTS.append(
                        f"(describe) field {field} declared {want} but "
                        f"payload_schema reports data_type={got!r} - "
                        f"Type4_StateLogicViolation - raw echo={str(ps.get(field))[:160]}")

        # ---- phase 3: invariant — data untouched by index creation ----
        cnt1, ok1 = get_count("count after create", C)
        if ok1 and cnt1 != N:
            DEFECTS.append(
                f"(count) points count {cnt1} != {N} after index creation - "
                f"Type4_StateLogicViolation "
                f"(qdrant_inv_index_toggle_preserves_data_001)")
        snap1, ok1s = scroll_payloads("scroll after create", C)
        if ok1s and snap1 != snap0:
            diff = {k for k in set(snap0) | set(snap1)
                    if snap0.get(k) != snap1.get(k)}
            DEFECTS.append(
                f"(payload) index creation mutated {len(diff)} point "
                f"payload(s): ids={sorted(diff)[:8]} - "
                f"Type4_StateLogicViolation "
                f"(qdrant_inv_index_toggle_preserves_data_001)")

        # ---- phase 4: delete all 8 indexes (wait=true) ----
        for field, _schema in FIELDS:
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": field},
                                  query_params={"wait": "true"})
            print(f"[delete {field}] status={s} raw={str(raw)[:200]}")
            if s in (200, 201):
                continue
            if s == 0 or 500 <= s <= 599:
                if not liveness(f"delete {field}"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(delete {field}) status {s} while /healthz alive - "
                    f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            else:
                DEFECTS.append(
                    f"(delete {field}) existing index delete rejected with "
                    f"HTTP {s} - Type1_IllegalSuccess - raw={str(raw)[:160]}")

        # ---- phase 5: no schema residue + data STILL untouched ----
        ps2, okps2 = describe_payload_schema("describe after delete", C)
        if okps2:
            residue = [f for f, _ in FIELDS if f in ps2]
            if residue:
                DEFECTS.append(
                    f"(describe) deleted indexes still present in "
                    f"payload_schema: {residue} - Type4_StateLogicViolation "
                    f"- echo={str(ps2)[:200]}")
        cnt2, ok2 = get_count("count after delete", C)
        if ok2 and cnt2 != N:
            DEFECTS.append(
                f"(count) points count {cnt2} != {N} after full index toggle - "
                f"Type4_StateLogicViolation "
                f"(qdrant_inv_index_toggle_preserves_data_001)")
        snap2, ok2s = scroll_payloads("scroll after delete", C)
        if ok2s and snap2 != snap0:
            diff = {k for k in set(snap0) | set(snap2)
                    if snap0.get(k) != snap2.get(k)}
            DEFECTS.append(
                f"(payload) full index toggle mutated {len(diff)} point "
                f"payload(s): ids={sorted(diff)[:8]} - "
                f"Type4_StateLogicViolation "
                f"(qdrant_inv_index_toggle_preserves_data_001)")

        # ---- summary ----
        print(f"[summary] enum creates={len(FIELDS)} describe_echo="
              f"{'ok' if okps else 'n/a'} counts="
              f"{[cnt0, cnt1 if ok1 else None, cnt2 if ok2 else None]} "
              f"payload_stable={snap0 == snap1 if ok1s else 'n/a'}/"
              f"{snap0 == snap2 if ok2s else 'n/a'}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("index toggle over the full PayloadSchemaType domain complete: "
              "8/8 valid creates 200 + persisted with matching data_type; "
              "count=12 and payload snapshot identical across the whole "
              "create/delete lifecycle; no schema residue - NO_DEFECT")
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
