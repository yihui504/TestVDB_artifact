#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_index_delete_003
# strategy: behavioral_disposition_faces
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (Boundary Default Optimism — the documented 200/200/404 face
#            triangle is assumed to hold exactly; a 200 leaking onto the
#            missing-collection face, or a 404 leaking onto the live-collection
#            faces, would mean the face split is not actually implemented)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: behavioral disposition faces x qdrant_behavioral_index_delete_001 (promise:
  "index deletion (existing or not) returns HTTP 200; missing collection returns
  404") — the three faces of the same DELETE endpoint are exercised back-to-back so
  any disposition leakage between faces is directly observable (G9: asymmetric
  disposition of the same operation across its faces is itself a defect signal):
  face-1 live collection + EXISTING index -> exactly 200; face-2 live collection +
  NON-EXISTENT field -> exactly 200 (not 404: a 404 here confuses "missing
  collection" with "missing index"); face-3 NEVER-CREATED ghost collection
  (fresh unique name, nothing to clean up) -> exactly 404 (a 200 here reports
  success for an operation on a resource that does not exist — phantom success).
  Type-2 diagnostics on the 404 leg are recorded measured-only (the error body
  structure is implementation detail per the threat model's by-design list; no
  defect claim from error wording alone). 200 envelopes are checked against the
  response_shape grid (result: object, result.status: string), non-object results
  printed SHAPE_CONFLICT measured-only (D3b conflict-zone discipline).
  [chunk_index+delete coverage: behavioral_disposition_faces x
  qdrant_behavioral_index_delete_001 (existing-200 face, non-existent-200 face,
  missing-collection-404 face)]
Oracle: face-1 (existing index, live bidl3_* collection) returns exactly HTTP 200
  (non-200 = legal input rejected, Type1_IllegalSuccess signal); face-2
  (non-existent field on the live collection) returns exactly HTTP 200 (404/409 =
  face-confusion against the "existing or not -> 200" promise, Type1_IllegalSuccess
  signal); face-3 (never-created ghost collection) returns exactly HTTP 404 (200 =
  phantom success on a missing resource = Type4_StateLogicViolation; 5xx/transport
  = Type3_RuntimeFailure with /healthz liveness re-check).
Constraint: qdrant_behavioral_index_delete_001 (bare id) — "index deletion (existing
  or not) returns HTTP 200; missing collection returns 404" (evidence_tier:
  explicit; level: endpoint)

Path registry (URLs verbatim from raw_knowledge.json api_endpoints[].url):
  index+delete       -> DELETE /collections/{collection_name}/index/{field_name}
  index+create       -> PUT    /collections/{collection_name}/index
  collections+create -> PUT    /collections/{collection_name}
  collections+get    -> GET    /collections/{collection_name}
  points+upsert      -> PUT    /collections/{collection_name}/points
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
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'drop_collection') if k in rt.PATHS]}")


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


def check_200_envelope(tag, status, raw):
    """200 leg vs response_shape grid: result must be an object with a string
    status. Non-conforming = SHAPE_CONFLICT measured-only print."""
    if status not in (200, 201):
        return
    b = parse_json(raw)
    res = (b or {}).get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        print(f"[{tag}] SHAPE_CONFLICT(measured-only): result is "
              f"{type(res).__name__}, response_shape declares object — "
              f"raw={str(raw)[:160]}")
        return
    if not isinstance(res.get("status"), str):
        print(f"[{tag}] SHAPE_CONFLICT(measured-only): result.status is "
              f"{type(res.get('status')).__name__}, declared string — "
              f"raw={str(raw)[:160]}")
    else:
        print(f"[{tag}] envelope ok: result.status={res.get('status')!r} "
              f"operation_id={res.get('operation_id')!r}")


def transport_or_5xx(tag, status, raw, defects):
    """Shared 0/5xx branch: liveness re-check, Type3 defect or script error.
    Returns True if a conclusion was recorded, False on script-error."""
    if not liveness(tag):
        return False
    defects.append(f"({tag}) status {status} while /healthz alive - "
                   f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "bidl3_" + TS + "_"
    C = PFX + "col"                 # this script creates and cleans up this one
    GHOST = PFX + "ghost_missing"   # NEVER created (404 leg; nothing to clean up)
    FLD = "f_kw"
    FLD_MISSING = "f_never_indexed"
    DEFECTS = []
    N = 3

    pts = [
        {"id": i,
         "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {FLD: f"kw{i}"}}
        for i in range(1, N + 1)
    ]

    try:
        # ---- setup: live collection + points + one keyword index ----
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
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": FLD,
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup create index {FLD}] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- face 1: live collection + EXISTING index -> exactly 200 ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FLD},
                              query_params={"wait": "true"})
        print(f"[face 1 existing-index delete] status={s} raw={str(raw)[:250]}")
        if s in (200, 201):
            check_200_envelope("face 1", s, raw)
        elif s == 0 or 500 <= s <= 599:
            if not transport_or_5xx("face 1", s, raw, DEFECTS):
                return "SCRIPT_ERROR"
        else:
            DEFECTS.append(f"(face 1) existing-index delete on live collection "
                           f"got HTTP {s}, promise says exactly 200 - legal input "
                           f"rejected - Type1_IllegalSuccess signal - "
                           f"raw={str(raw)[:160]} "
                           f"(qdrant_behavioral_index_delete_001)")

        # ---- face 2: live collection + NON-EXISTENT field -> exactly 200 ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FLD_MISSING},
                              query_params={"wait": "true"})
        print(f"[face 2 non-existent-field delete] status={s} raw={str(raw)[:250]}")
        if s in (200, 201):
            check_200_envelope("face 2", s, raw)
        elif s == 0 or 500 <= s <= 599:
            if not transport_or_5xx("face 2", s, raw, DEFECTS):
                return "SCRIPT_ERROR"
        else:
            DEFECTS.append(f"(face 2) non-existent-field delete on LIVE collection "
                           f"got HTTP {s}, promise says 'existing or not -> 200' "
                           f"(404 here confuses missing-collection with "
                           f"missing-index) - Type1_IllegalSuccess signal - "
                           f"raw={str(raw)[:160]} "
                           f"(qdrant_behavioral_index_delete_001)")

        # ---- face 3: NEVER-CREATED ghost collection -> exactly 404 ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": GHOST, "field_name": FLD},
                              query_params={"wait": "true"})
        print(f"[face 3 missing-collection delete] status={s} raw={str(raw)[:250]}")
        if s == 404:
            # Type-2 diagnostics: measured-only (error body structure is
            # implementation detail per threat model by-design list)
            low = str(raw).lower()
            names_collection = (GHOST.lower() in low) or ("collection" in low)
            print(f"[face 3 diagnostics measured-only] names-collection-or-cause="
                  f"{names_collection} raw={str(raw)[:200]}")
        elif s in (200, 201):
            DEFECTS.append(f"(face 3) delete on NEVER-CREATED collection {GHOST} "
                           f"returned HTTP {s} — phantom success for an operation "
                           f"on a missing resource, promise says exactly 404 - "
                           f"Type4_StateLogicViolation - raw={str(raw)[:160]} "
                           f"(qdrant_behavioral_index_delete_001)")
            check_200_envelope("face 3", s, raw)
        elif s == 0 or 500 <= s <= 599:
            if not transport_or_5xx("face 3", s, raw, DEFECTS):
                return "SCRIPT_ERROR"
        else:
            DEFECTS.append(f"(face 3) missing-collection delete got HTTP {s}, "
                           f"promise says exactly 404 - disposition outside the "
                           f"documented triangle - Type4_StateLogicViolation - "
                           f"raw={str(raw)[:160]} "
                           f"(qdrant_behavioral_index_delete_001)")

        # ---- summary ----
        print(f"[summary] faces probed=3 (existing-200 / non-existent-200 / "
              f"missing-collection-404); defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("disposition triangle holds exactly: existing-index delete 200, "
              "non-existent-field delete 200 on the live collection, "
              "never-created collection 404 — no face leakage - NO_DEFECT")
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
