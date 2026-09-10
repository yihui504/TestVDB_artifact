#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_004
# strategy: count_consistency
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_002
# source_url: https://qdrant.tech/documentation/manage-data/vectors/
# doc_version: current (site latest; no version archive)
"""
Attack: state readback of sparse_vectors on PUT /collections/{name}
  (collections+create). The type constraint promises sparse_vectors is a map
  of vector-name -> SparseVectorParams and that sparse distance IS Dot and is
  not user-settable. Legs:
  (A) create dense {size:4,Cosine} + sparse_vectors {"text": {}} (empty
  params — the documented default form) -> 200; readback
  result.config.params.sparse_vectors must contain the "text" key (created
  state mirrors the requested map).
  (B) sparse with an explicit non-Dot distance: sparse_vectors
  {"text": {"distance": "Cosine"}} -> either rejected (4xx, clean) or, if
  accepted, readback MUST show distance Dot (forced to the only legal
  sparse metric). Accepted AND persisted as a non-Dot distance = the stored
  state violates "sparse vector distance IS Dot".
  (C) sparse_vectors as a NON-map (array) -> type violation -> 4xx and no
  residue (describe 404).
  [chunk_collections+create-1of2 coverage: count_consistency (state-equality
  readback) x qdrant_type_collections_create_002]
Oracle: (A) create -> 200 and readback sparse_vectors contains key "text";
  (B) 4xx rejection OR 2xx with readback sparse distance forced to "Dot"
  (persisted non-Dot = Type4_StateLogicViolation; silent 2xx acceptance
  judged only via readback); (C) 4xx + describe 404 (residue = Type4)
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


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def read_sparse(name):
    """GET describe -> (status, sparse_map_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200 or not raw:
        return s, None, raw
    try:
        b = json.loads(raw)
        cfg = ((b or {}).get("result") or {}).get("config")
        sp = ((cfg or {}).get("params") or {}).get("sparse_vectors") if isinstance(cfg, dict) else None
        return s, (sp if isinstance(sp, dict) else None), raw
    except (json.JSONDecodeError, ValueError, TypeError):
        return s, None, raw


def liveness_ok(tag):
    hs, hraw = safe_request("GET", "healthz")
    print(f"[{tag} liveness] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr4_" + TS + "_"
    CA = PFX + "sparse_default"
    CB = PFX + "sparse_cosdist"
    CC = PFX + "sparse_notmap"
    DEFECTS = []

    try:
        # ---- (A) documented default sparse map form ----
        sA, rA = safe_request("PUT", "create_collection", path_params={"name": CA},
                              body={"vectors": {"size": 4, "distance": "Cosine"},
                                    "sparse_vectors": {"text": {}}})
        print(f"[A create] status={sA} raw={rA[:300]}")
        if sA == 0 or 500 <= sA <= 599:
            if not liveness_ok("A"):
                return "SCRIPT_ERROR"
            if 500 <= sA <= 599:
                DEFECTS.append(
                    f"(A) sparse create returned {sA} (5xx, service alive per "
                    f"/healthz) — Type3_RuntimeFailure — raw={rA[:200]}"
                )
        elif sA not in (200, 201):
            print(f"SETUP_ERROR: documented sparse create rejected with {sA} — "
                  f"cannot judge readback; recorded as legal-input rejection")
            DEFECTS.append(
                f"(A) sparse_vectors map create (documented form) rejected with "
                f"{sA} — legal input wrongly rejected — raw={rA[:200]}"
            )
        else:
            gs, sp, graw = read_sparse(CA)
            print(f"[A readback] status={gs} sparse={json.dumps(sp)[:300] if sp else graw[:200]}")
            if gs != 200:
                print("SETUP_ERROR: readback failed")
                return "SCRIPT_ERROR"
            if sp is None or "text" not in (sp or {}):
                DEFECTS.append(
                    f"(A) sparse_vectors state lost after successful create: "
                    f"readback={sp!r} (expected map containing 'text') — "
                    f"Type4_StateLogicViolation"
                )
            else:
                td = (sp.get("text") or {})
                if isinstance(td, dict) and td.get("distance") not in (None, "Dot"):
                    DEFECTS.append(
                        f"(A) default sparse readback distance={td.get('distance')!r} "
                        f"(assertion: sparse distance IS Dot) — "
                        f"Type4_StateLogicViolation"
                    )

        # ---- (B) explicit non-Dot sparse distance ----
        sB, rB = safe_request("PUT", "create_collection", path_params={"name": CB},
                              body={"vectors": {"size": 4, "distance": "Cosine"},
                                    "sparse_vectors": {"text": {"distance": "Cosine"}}})
        print(f"[B create non-Dot sparse distance] status={sB} raw={rB[:300]}")
        if sB == 0:
            if not liveness_ok("B"):
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (B); liveness ok — skipped")
        elif 500 <= sB <= 599:
            if not liveness_ok("B"):
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(B) non-Dot sparse distance create returned {sB} (5xx; service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={rB[:200]}"
            )
        elif 200 <= sB < 300:
            gs, sp, graw = read_sparse(CB)
            print(f"[B readback] status={gs} sparse={json.dumps(sp)[:300] if sp else graw[:200]}")
            if gs == 200 and isinstance(sp, dict) and "text" in sp:
                td = sp.get("text") or {}
                dist = td.get("distance") if isinstance(td, dict) else None
                if dist == "Dot" or dist is None:
                    print(f"OBSERVATION (B): non-Dot request accepted but state "
                          f"normalized to distance={dist!r} — consistent with "
                          f"'not user-settable' assertion")
                else:
                    DEFECTS.append(
                        f"(B) sparse vector persisted with distance={dist!r} — "
                        f"assertion 'sparse vector distance IS Dot (not "
                        f"user-settable)' violated in stored state — "
                        f"Type4_StateLogicViolation — raw={graw[:200]}"
                    )
            else:
                print("OBSERVATION (B): accepted but readback unavailable — "
                      f"state unjudgeable")
        elif sB in (400, 422):
            print("[B] clean rejection of user-settable sparse distance (as "
                  "asserted 'not user-settable')")
        else:
            print(f"OBSERVATION (B): status {sB} outside promise set — recorded")

        # ---- (C) sparse_vectors as non-map (array) -> reject + no residue ----
        sC, rC = safe_request("PUT", "create_collection", path_params={"name": CC},
                              body={"vectors": {"size": 4, "distance": "Cosine"},
                                    "sparse_vectors": [{"name": "text"}]})
        print(f"[C create non-map sparse] status={sC} raw={rC[:300]}")
        if sC == 0:
            if not liveness_ok("C"):
                return "SCRIPT_ERROR"
            print("ENV_ISSUE: transport failure on (C); liveness ok — skipped")
        elif 500 <= sC <= 599:
            if not liveness_ok("C"):
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"(C) non-map sparse_vectors returned {sC} (5xx; service alive "
                f"per /healthz) — Type3_RuntimeFailure — raw={rC[:200]}"
            )
        elif 200 <= sC < 300:
            DEFECTS.append(
                f"(C) sparse_vectors as array accepted with {sC} — map type "
                f"violated — Type1_IllegalSuccess — raw={rC[:200]}"
            )
        elif sC not in (400, 422):
            print(f"OBSERVATION (C): rejection status {sC} outside 400/422 — recorded")
        # no-residue probe applies regardless
        gsc, _, gcraw = safe_request("GET", "describe_collection", path_params={"name": CC})
        if gsc == 200:
            DEFECTS.append(
                f"(C) rejected/invalid sparse create left residue: describe -> "
                f"200 — ghost state — Type4_StateLogicViolation — "
                f"raw={gcraw[:200]}"
            )

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in (CA, CB, CC):
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
