#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_index_delete_006
# strategy: illegal_rejection
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01-flavored face variant (a validator that only accepts
#   'simple' field names or chokes on documented optional query params
#   would wrongly reject LEGAL deletes; the assertion '(existing or not)
#   returns HTTP 200' makes every well-formed delete on an existing
#   collection a legal 200)
"""
Attack: illegal_rejection (S3, Type-1 reverse, G3 generalization) x
  assertions::qdrant_behavioral_index_delete_001 on index+delete
  (chunk_index+delete unit assertions::qdrant_behavioral_index_delete_001 -
  expected_behavior: "index deletion (existing or not) returns HTTP 200;
  missing collection returns 404", evidence_tier=explicit, endpoint level).
  Not whether illegal input is accepted, but whether LEGAL deletes are
  wrongly rejected. G3 generalization: the same-shape family beyond the
  single already-known case - existing index / never-indexed field /
  already-deleted field / dotted-path field name (documented nested
  payload addressing per the payload/indexing docs in raw_knowledge) /
  documented optional query params (wait, timeout) present.
  R22 chunk_index+delete semantic coverage map: see _001 (this script =
  slot 6 of 6: illegal_rejection x behavioral_index_delete_001).
Oracle: on a self-created collection (premise verified: keyword index on
  cat echoed in describe result.payload_schema), EVERY well-formed DELETE
  index call answers HTTP 200 - leg 1 existing index cat (the plain
  case); leg 2 never-indexed unknown field; leg 3 the ALREADY-DELETED
  field again (repeat idempotence); leg 4 dotted-path field lvl.tag -
  whether or not its create succeeded (a refused/absent create only moves
  the leg into the 'non-existent index' branch, which the assertion ALSO
  promises as 200 - so 200 is required either way, and a 4xx create is
  printed as a measured note about the create face, not this face);
  leg 5 with the documented optional query params wait=true and
  timeout=30 present. Any 4xx on these legal deletes = Type1_
  IllegalRejection; any 5xx = Type3_RuntimeFailure after a /healthz
  liveness re-check; a 200 whose envelope result is not an object =
  Type4_StateLogicViolation (index+delete response_shape declares
  result:object, result.status:string, result.operation_id:integer|null);
  transport/setup failures never produce defect conclusions (G8). The
  missing-collection 404 branch is NOT re-tested here (it is _001 leg 3 /
  _005 - a legal name on an existing collection is this script's scope).

Constraint anchor qdrant_behavioral_index_delete_001 (explicit, endpoint
level):
  description: "returns 200 ok; a missing collection returns 404"
  (source_url https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index,
  doc_version 1.18.x (versioned v-1-18-x api-reference)).

URL derivation: raw_knowledge api_endpoints[index+delete].url is
  /collections/{collection_name}/index/{field_name}; runtime PATHS keys
  only (delete_index/create_index/describe_collection/upsert_points/
  healthz). R15-R21 lessons honored: bare constraint IDs; unique prefix;
  wait string-form query param ("true", not boolean True - v34 R1 S1
  lesson; timeout likewise an integer-valued query param); cleanup drops
  only script-owned collections.
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

PFX = "sidl06" + uuid.uuid4().hex[:6]
DIM = 4
COL = PFX + "_live"
FIELD = "cat"
GHOST = "ghost_never_indexed"
DOTTED = "lvl.tag"   # documented nested-payload addressing (dotted path)


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


def delete_index(field, tag="", query_params=None):
    qp = {"wait": "true"}
    if query_params:
        qp.update(query_params)
    st, raw = safe_request("DELETE", "delete_index",
                           path_params={"name": COL, "field_name": field},
                           query_params=qp, timeout=30)
    print(f"[DELETE index{(' ' + tag) if tag else ''} {COL}/{field}] qp={qp} -> "
          f"status={st} raw={str(raw)[:300]}")
    return st, raw


def require_legal_200(st, raw, label, legal_desc):
    """A well-formed DELETE on an EXISTING collection must be 200
    ('index deletion (existing or not) returns HTTP 200')."""
    transport_guard(label, st, raw)
    if 400 <= st < 500:
        defect("Type1_IllegalRejection",
               f"LEGAL delete wrongly rejected: {legal_desc} answered HTTP {st} on the "
               f"EXISTING collection {COL}; the assertion promises 'index deletion "
               f"(existing or not) returns HTTP 200': {str(raw)[:300]!r}")
    if st != 200:
        # non-4xx non-5xx non-200 (e.g. 3xx) - branch violation
        defect("Type4_StateLogicViolation",
               f"{legal_desc} answered HTTP {st}; the assertion promises exactly 200 "
               f"for deletes on an existing collection: {str(raw)[:300]!r}")
    body = jload(raw)
    res = body.get("result") if isinstance(body, dict) else None
    if not isinstance(res, dict):
        defect("Type4_StateLogicViolation",
               f"{label}: 200 envelope result is not an object: {str(raw)[:300]!r} "
               f"(index+delete response_shape declares result:object, "
               f"result.status:string, result.operation_id:integer|null)")
    print(f"[{label}] 200 result.status={res.get('status')!r} "
          f"result.operation_id={res.get('operation_id')!r}")


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception as e:
        print(f"cleanup warning (drop {COL}): {e}")


def main():
    print(f"ownership prefix: {PFX}")
    print("[assertion quote] expected_behavior: 'index deletion (existing or not) "
          "returns HTTP 200; missing collection returns 404'")
    try:
        # ---- premise: collection with data + a real keyword index on cat ----
        ok, err = rt.setup_default(COL, dim=DIM, metric="Cosine")
        if not ok:
            script_error(f"premise create {COL} failed: {err}")
        pts = [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4],
                "payload": {"cat": "A" if i % 2 else "B", "lvl": {"tag": f"t{i}"}}}
               for i in range(1, 3)]
        st, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=30)
        transport_guard("setup upsert", st, raw)
        if st not in (200, 201):
            script_error(f"setup upsert failed: {st} {str(raw)[:200]}")
        st, raw = safe_request("PUT", "create_index",
                               body={"field_name": FIELD, "field_schema": "keyword"},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=30)
        transport_guard("premise index create", st, raw)
        # premise echo check
        st, raw = safe_request("GET", "describe_collection", path_params={"name": COL},
                               timeout=30)
        res = jload(raw).get("result") if isinstance(jload(raw), dict) else None
        echoed = False
        if isinstance(res, dict):
            for container in ("payload_schema", "payload_indexes"):
                v = res.get(container)
                if isinstance(v, dict) and FIELD in v:
                    echoed = True
        if not echoed:
            script_error(f"premise: index on {FIELD!r} not echoed in describe")
        print(f"[premise] {COL}: 2 points + keyword index on {FIELD!r} echoed")

        # ---- leg 1: existing index (the plain legal case) ----
        st, raw = delete_index(FIELD, "leg1 existing")
        require_legal_200(st, raw, "leg1", f"delete of the EXISTING index {FIELD!r}")

        # ---- leg 2: never-indexed unknown field (idempotent branch) ----
        st, raw = delete_index(GHOST, "leg2 never-indexed")
        require_legal_200(st, raw, "leg2",
                          f"delete of the NEVER-INDEXED field {GHOST!r} "
                          f"(non-existent index, idempotent branch)")

        # ---- leg 3: already-deleted field again (repeat idempotence) ----
        st, raw = delete_index(FIELD, "leg3 already-deleted")
        require_legal_200(st, raw, "leg3",
                          f"REPEAT delete of the already-deleted index {FIELD!r}")

        # ---- leg 4: dotted-path field name (documented nested addressing) ----
        st, raw = safe_request("PUT", "create_index",
                               body={"field_name": DOTTED, "field_schema": "keyword"},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=30)
        transport_guard("leg4 dotted create", st, raw)
        if 400 <= st < 500:
            print(f"[leg4 note] create of dotted-path index {DOTTED!r} was refused "
                  f"({st}) on the CREATE face - measured note (create-face legality is "
                  f"R21's chunk); the delete leg below then exercises the "
                  f"non-existent-index idempotence branch, which the assertion also "
                  f"promises as 200")
        else:
            print(f"[leg4 note] dotted-path create answered {st} (echo/legality of the "
                  f"create face is out of scope here; delete branch below is "
                  f"'existing index' in that case)")
        st, raw = delete_index(DOTTED, "leg4 dotted-path")
        require_legal_200(st, raw, "leg4",
                          f"delete of the dotted-path field index {DOTTED!r} (existing "
                          f"or not, 200 is promised either way)")

        # ---- leg 5: documented optional query params present (wait + timeout) ----
        st, raw = delete_index(GHOST, "leg5 qp", query_params={"timeout": 30})
        require_legal_200(st, raw, "leg5",
                          f"delete with the documented optional query params "
                          f"wait=true and timeout=30 present ({GHOST!r})")

        print("OK: every legal delete variant answered 200 with a result:object "
              "envelope - existing index, never-indexed field, already-deleted "
              "repeat, dotted-path field, and wait/timeout query params")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
