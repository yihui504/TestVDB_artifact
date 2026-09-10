#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_delete_001
# strategy: delete_consistency
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: status-vs-state contract for DELETE /collections/{name}
  (collections+delete; URL from raw_knowledge api_endpoints[].url).
  The assertion promises: DELETE on an existing collection is confirmed
  with 200; DELETE on a non-existent collection returns 404, NOT 200.
  G4 positive/negative pairing on the same name space:
  (A negative) DELETE a never-created unique name -> must be 404
      (a 200 here = Type1_IllegalSuccess: server confirms deleting
      something that never existed).
      NOTE: threat_model's by-design "idempotent DELETE returns 200 for
      non-existent" is POINT-scoped (DELETE /collections/{c}/points),
      not collection-scoped; this assertion explicitly pins 404 for a
      non-existent collection, so no by-design skip applies here.
  (B setup) create the collection -> 200 (setup gate).
  (C positive) DELETE the existing collection -> must be 200 exactly.
  (D negative repeat) immediately DELETE the same name again -> must be
      404 (double delete; a 200 = the first "confirmed" delete left the
      name registered = ghost state).
  (E lifecycle closure) recreate the same name after the confirmed
      delete -> 200 (a 409/400 = the delete never fully released the
      name = residue).
  [chunk_collections+delete coverage: delete_consistency x
   qdrant_behavioral_collections_delete_001 (existing=200 /
   non-existent=404 / double-delete=404 / name-reuse)]
Oracle: never-created DELETE -> 404; existing DELETE -> 200; immediate
  second DELETE -> 404; recreate-after-delete -> 200. Any 2xx on a
  non-existent (never-created or already-deleted) name = Type1_
  IllegalSuccess; non-200 on a verified-existing collection = Type4_
  StateLogicViolation; 5xx judged Type3 only after /healthz confirms
  liveness.
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


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
        return b if isinstance(b, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scdl1_" + TS + "_"
    C = PFX + "del"
    NEVER = PFX + "never_created"
    DEFECTS = []

    def liveness(tag, status, raw):
        print(f"[liveness {tag}] healthz probe required for status={status}")
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    try:
        # ---- (A negative) delete a never-created collection -> 404 ----
        a_s, a_raw = safe_request("DELETE", "drop_collection", path_params={"name": NEVER})
        print(f"[A delete-never-created] status={a_s} raw={a_raw[:200]}")
        if a_s == 0:
            # transport failure: liveness re-check before any conclusion (D3b r3)
            liveness("A", a_s, a_raw)
            return "SCRIPT_ERROR"
        if 500 <= a_s <= 599:
            if liveness("A", a_s, a_raw):
                DEFECTS.append(f"(A) DELETE never-created collection returned {a_s} "
                               f"with service alive — Type3_RuntimeFailure — "
                               f"raw={a_raw[:200]}")
            else:
                return "SCRIPT_ERROR"
        elif 200 <= a_s <= 299:
            DEFECTS.append(f"(A) DELETE never-created collection returned {a_s} "
                           f"(assertion pins 404, NOT 200) — Type1_IllegalSuccess "
                           f"— raw={a_raw[:200]} "
                           f"(qdrant_behavioral_collections_delete_001)")
        elif a_s != 404:
            DEFECTS.append(f"(A) DELETE never-created collection returned {a_s} "
                           f"(expected 404) — inconsistent disposition — "
                           f"Type4_StateLogicViolation — raw={a_raw[:200]}")

        # ---- (B setup) create -> 200 ----
        b_s, b_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"[B create] status={b_s} raw={b_raw[:200]}")
        if b_s == 0 or 500 <= b_s <= 599 or b_s not in (200, 201):
            print(f"SETUP_ERROR: create returned {b_s} — cannot judge delete contract")
            return "SCRIPT_ERROR"
        sanity_s, sanity_raw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[B describe-sanity] status={sanity_s}")
        if sanity_s != 200:
            print(f"SETUP_ERROR: created collection not describable ({sanity_s})")
            return "SCRIPT_ERROR"

        # ---- (C positive) delete existing -> exactly 200 ----
        c_s, c_raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[C delete-existing] status={c_s} raw={c_raw[:200]}")
        if c_s == 0:
            return "SCRIPT_ERROR"
        if 500 <= c_s <= 599:
            if liveness("C", c_s, c_raw):
                DEFECTS.append(f"(C) DELETE existing collection returned {c_s} with "
                               f"service alive — Type3_RuntimeFailure — raw={c_raw[:200]}")
            else:
                return "SCRIPT_ERROR"
        elif c_s != 200:
            DEFECTS.append(f"(C) DELETE on a verified-existing collection returned "
                           f"{c_s} (assertion: confirmed with 200) — server misjudges "
                           f"existence — Type4_StateLogicViolation — raw={c_raw[:200]}")

        # ---- (D negative repeat) immediate double delete -> 404 ----
        d_s, d_raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[D double-delete] status={d_s} raw={d_raw[:200]}")
        if d_s == 0:
            return "SCRIPT_ERROR"
        if 500 <= d_s <= 599:
            if liveness("D", d_s, d_raw):
                DEFECTS.append(f"(D) second DELETE returned {d_s} with service alive "
                               f"— Type3_RuntimeFailure — raw={d_raw[:200]}")
            else:
                return "SCRIPT_ERROR"
        elif 200 <= d_s <= 299:
            DEFECTS.append(f"(D) DELETE of the already-deleted name returned {c_s}->"
                           f"{d_s} 2xx (expected 404; the first 200-confirmed delete "
                           f"left the name answering) — Type1_IllegalSuccess — "
                           f"raw={d_raw[:200]} (qdrant_behavioral_collections_delete_001)")
        elif d_s != 404:
            DEFECTS.append(f"(D) second DELETE returned {d_s} (expected 404) — "
                           f"Type4_StateLogicViolation — raw={d_raw[:200]}")

        # ---- (E lifecycle closure) recreate same name -> 200 ----
        e_s, e_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"[E recreate] status={e_s} raw={e_raw[:200]}")
        if e_s == 0:
            return "SCRIPT_ERROR"
        if 500 <= e_s <= 599:
            if liveness("E", e_s, e_raw):
                DEFECTS.append(f"(E) recreate after confirmed delete returned {e_s} "
                               f"with service alive — Type3_RuntimeFailure — "
                               f"raw={e_raw[:200]}")
            else:
                return "SCRIPT_ERROR"
        elif e_s != 200:
            DEFECTS.append(f"(E) recreate of a deleted (404-confirmed) name returned "
                           f"{e_s} (expected 200: a confirmed delete must fully "
                           f"release the name) — delete residue — "
                           f"Type4_StateLogicViolation — raw={e_raw[:200]}")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
