#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_delete_002
# strategy: behavioral_contract
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the state promise "deleting a
#   non-existent payload index succeeds (idempotent success, 200); deleting
#   an index does not delete the underlying data" is exercised in BOTH
#   directions: the idempotent-success positive AND the destructive
#   negative construction - a delete that answers 200 while silently
#   dropping point rows/payloads/vectors)
"""
Attack: behavioral_contract (S1, G4 positive/negative pairing) x
  constraints::qdrant_state_index_delete_001 on index+delete
  (chunk_index+delete unit constraints::qdrant_state_index_delete_001,
  evidence_tier=explicit, level=system - general-scenario both-direction
  coverage per D2: positive exercises the idempotent-success promise;
  negative constructs the violation of the data-untouched promise).
  R22 chunk_index+delete semantic coverage map: see _001 (this script =
  slot 2 of 6: behavioral_contract x state_index_delete_001).
Oracle: with the premise verified (2 indexes echoed in describe
  result.payload_schema, 4 points readable), DELETE of a NEVER-INDEXED
  field answers HTTP 200 (idempotent-success promise exercised - 4xx =
  Type1_IllegalRejection) and changes NOTHING; DELETE of the two REAL
  indexes (cat keyword, score integer) answers 200 twice AND removes both
  entries from describe result.payload_schema (200-without-removal =
  Type4 silent no-op); after both real deletes the FULL row snapshot
  (4 rows: ids, payload dicts, vector lists, read back via scroll
  with_payload+with_vector and sorted by id) is IDENTICAL to the
  pre-delete baseline and POST /points/count exact still returns 4 -
  any lost/changed row, lost payload key, changed vector, or count drift
  = Type4_StateLogicViolation ("index deletion leaves point data
  untouched" is the constraint's own assertion); a second post-delete
  scroll re-read is also identical (read stability); 5xx with healthy
  /healthz = Type3_RuntimeFailure; transport/setup failures never
  produce defect conclusions (G8). Both readback vectors are f32
  round-trips from storage, so exact list equality between the two
  READBACKS is representation-safe (the originally sent floats are
  never compared).

Constraint anchor qdrant_state_index_delete_001 (explicit, system level):
  description: "deleting a non-existent payload index succeeds (idempotent
  success, 200); deleting an index does not delete the underlying data"
  assertion: "delete of a non-existent payload index is an idempotent
  success; index deletion leaves point data untouched"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index,
  doc_version 1.18.x (versioned v-1-18-x api-reference)).

Legs:
  leg 0 premise - create collection, upsert 4 points (payload cat/score/
      note + dim-4 vectors), create keyword index on cat + integer index
      on score (wait=true), verify BOTH echoed in describe;
  leg 1 positive-idempotent - DELETE ghost field (never indexed) -> 200
      and the baseline snapshot taken after it is unchanged by
      construction (the promise's own success branch);
  leg 2 removal-effect - DELETE cat + DELETE score -> 200 each + both
      entries gone from the describe payload index container (the 200s
      delivered actual removal, distinguishing a real delete from a
      silent no-op);
  leg 3 negative-data-untouched (the core) - post-delete snapshot:
      scroll rows byte-equal to baseline, count exact == 4;
  leg 4 control - a second post-delete scroll is again identical to the
      first (read stability, rules out a transient/flaky readback).

URL derivation: raw_knowledge api_endpoints[index+delete].url is
  /collections/{collection_name}/index/{field_name}; runtime PATHS keys
  only (delete_index/create_index/describe_collection/upsert_points/
  scroll/count/healthz). R15-R21 lessons honored: bare constraint IDs;
  envelope result.<field> extraction (scroll -> result.points, count ->
  result.count per points+scroll / points+count response_shape grids);
  unique prefix; wait as string-form query param; cleanup drops only
  script-owned collections. Scroll (deterministic full scan) is used
  instead of search on purpose - HNSW score-order oracles are by-design
  non-deterministic (threat model G3 avoidance).
"""
import os
import sys
import json
import time
import uuid
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
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
if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)
try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)
if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

PFX = "sidl02" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
N_PTS = 4
FIELDS = {"cat": "keyword", "score": "integer"}
GHOST = "ghost_field_never_indexed"


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                 timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def transport_guard(label, st, raw):
    if st <= 0 or 500 <= st <= 599:
        hs = liveness(label)
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"service down - '{label}' got status={st} and /healthz={hs}")
        if st <= 0:
            script_error(f"transport failure '{label}' with healthy /healthz: {str(raw)[:150]}")
        defect("Type3_RuntimeFailure",
               f"'{label}' got {st} with /healthz alive; raw={str(raw)[:250]}")
    return st


def put_index(name, field, schema):
    body = {"field_name": field, "field_schema": schema}
    st, raw = safe_request("PUT", "create_index", body=body,
                           path_params={"name": name},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[PUT index {name}/{field}] schema={schema} -> status={st} raw={str(raw)[:200]}")
    return st, raw


def delete_index(name, field, tag=""):
    st, raw = safe_request("DELETE", "delete_index",
                           path_params={"name": name, "field_name": field},
                           query_params={"wait": "true"}, timeout=30)
    print(f"[DELETE index{(' ' + tag) if tag else ''} {name}/{field}] -> status={st} raw={str(raw)[:200]}")
    return st, raw


def field_in_index_container(name, field):
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name},
                           timeout=30)
    if st != 200:
        script_error(f"describe {name} failed: {st} {str(raw)[:200]}")
    res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
    if not isinstance(res, dict):
        script_error(f"describe {name}: result not an object: {str(raw)[:200]}")
    for container in ("payload_schema", "payload_indexes"):
        v = res.get(container)
        if isinstance(v, dict) and field in v:
            return True
    return False


def snapshot(name, tag):
    """Deterministic full-row readback: scroll with_payload+with_vector,
    rows sorted by id. Returns list of {id, payload, vector} dicts."""
    st, raw = safe_request("POST", "scroll",
                           body={"limit": 100, "with_payload": True, "with_vector": True},
                           path_params={"name": name}, timeout=30)
    transport_guard(f"scroll {tag}", st, raw)
    if st != 200:
        script_error(f"scroll {tag} failed: {st} {str(raw)[:200]}")
    res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        defect("Type4_StateLogicViolation",
               f"scroll {tag}: result.points is not an array (points+scroll "
               f"response_shape declares result.points:array): {str(raw)[:300]!r}")
    rows = [{"id": p.get("id"), "payload": p.get("payload"), "vector": p.get("vector")}
            for p in pts if isinstance(p, dict)]
    rows.sort(key=lambda r: (str(type(r["id"])), r["id"]))
    print(f"[snapshot {tag}] {len(rows)} rows ids={[r['id'] for r in rows]}")
    return rows


def exact_count(name, tag):
    st, raw = safe_request("POST", "count", body={"exact": True},
                           path_params={"name": name}, timeout=30)
    transport_guard(f"count {tag}", st, raw)
    if st != 200:
        script_error(f"count {tag} failed: {st} {str(raw)[:200]}")
    res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
    cnt = res.get("count") if isinstance(res, dict) else None
    if not isinstance(cnt, int):
        defect("Type4_StateLogicViolation",
               f"count {tag}: result.count not an integer (points+count "
               f"response_shape declares result.count:integer): {str(raw)[:300]!r}")
    print(f"[count {tag}] exact={cnt}")
    return cnt


def rows_diff(base, post):
    """Localize the first difference between two sorted row snapshots."""
    if len(base) != len(post):
        return (f"row count {len(base)} -> {len(post)} "
                f"(ids {[r['id'] for r in base]} -> {[r['id'] for r in post]})")
    for b, p in zip(base, post):
        if b["id"] != p["id"]:
            return f"row id changed {b['id']!r} -> {p['id']!r}"
        if b["payload"] != p["payload"]:
            return f"row id={b['id']!r} payload {json.dumps(b['payload'])} -> {json.dumps(p['payload'])}"
        if b["vector"] != p["vector"]:
            return (f"row id={b['id']!r} vector {json.dumps(b['vector'])} -> "
                    f"{json.dumps(p['vector'])}")
    return None


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[constraint quote] assertion: 'delete of a non-existent payload index "
          "is an idempotent success; index deletion leaves point data untouched'")
    try:
        # ---- leg 0: premise - collection, 4 data points, 2 echoed indexes ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        pts = [{"id": i,
                "vector": [round(0.1 * i, 4), 0.2, 0.3, -0.4],
                "payload": {"cat": "A" if i % 2 else "B", "score": 10 * i,
                            "note": f"keep{i}"}}
               for i in range(1, N_PTS + 1)]
        st, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=30)
        transport_guard("setup upsert", st, raw)
        if st not in (200, 201):
            script_error(f"setup upsert failed: {st} {str(raw)[:200]}")
        for field, schema in FIELDS.items():
            st, raw = put_index(COL, field, schema)
            transport_guard(f"setup index {field}", st, raw)
            if st != 200 or not field_in_index_container(COL, field):
                script_error(f"premise: index on {field!r} not echoed (status={st})")
        if exact_count(COL, "premise") != N_PTS:
            script_error("premise: count != 4 before any delete")
        print(f"[premise] {COL}: 4 points + indexes on {sorted(FIELDS)}")

        # ---- leg 1: positive-idempotent - ghost delete is a 200 no-op ----
        st, raw = delete_index(COL, GHOST, "leg1 ghost")
        transport_guard("leg1 ghost delete", st, raw)
        if st != 200:
            defect("Type1_IllegalRejection" if 400 <= st < 500 else "Type4_StateLogicViolation",
                   f"DELETE of NON-EXISTENT index {GHOST!r} on EXISTING collection {COL} "
                   f"answered HTTP {st}; the state constraint promises idempotent success "
                   f"200: {str(raw)[:300]!r}")

        # ---- baseline snapshot AFTER the idempotent ghost delete ----
        base = snapshot(COL, "baseline")
        if len(base) != N_PTS:
            defect("Type4_StateLogicViolation",
                   f"baseline readback has {len(base)} rows (expected {N_PTS}) before any "
                   f"real index delete - setup or ghost-delete corrupted data")

        # ---- leg 2: removal-effect - both REAL indexes deleted, entries gone ----
        for field in sorted(FIELDS):
            st, raw = delete_index(COL, field, "leg2 real")
            transport_guard(f"leg2 delete {field}", st, raw)
            if st != 200:
                defect("Type1_IllegalRejection" if 400 <= st < 500 else "Type4_StateLogicViolation",
                       f"DELETE of EXISTING index {field!r} answered HTTP {st}; 200 is "
                       f"promised: {str(raw)[:300]!r}")
            if field_in_index_container(COL, field):
                defect("Type4_StateLogicViolation",
                       f"DELETE of index {field!r} answered 200 but the field is STILL "
                       f"echoed in the describe payload index container - 200-without-"
                       f"removal silent no-op (the 200 promises the index left)")

        # ---- leg 3: negative-data-untouched - the core promise ----
        post = snapshot(COL, "post-delete")
        d = rows_diff(base, post)
        if d:
            defect("Type4_StateLogicViolation",
                   f"index deletion changed point data - '{d}' - the state constraint "
                   f"asserts 'index deletion leaves point data untouched' (both real "
                   f"indexes deleted with 200 above)")
        if exact_count(COL, "post-delete") != N_PTS:
            defect("Type4_StateLogicViolation",
                   f"exact count after index deletion is not {N_PTS} - point data was "
                   f"touched by index deletion")

        # ---- leg 4: control - read stability ----
        again = snapshot(COL, "post-delete-re-read")
        d2 = rows_diff(post, again)
        if d2:
            defect("Type4_StateLogicViolation",
                   f"post-delete readback is unstable between two reads - '{d2}' "
                   f"(first read matches baseline, so this is not index-deletion "
                   f"damage but a consistency violation on the same face)")

        print(f"OK: ghost delete 200 (idempotent); real deletes 200 + entries removed; "
              f"all {N_PTS} rows (ids/payloads/vectors) and exact count unchanged after "
              f"index deletion; re-read stable")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
