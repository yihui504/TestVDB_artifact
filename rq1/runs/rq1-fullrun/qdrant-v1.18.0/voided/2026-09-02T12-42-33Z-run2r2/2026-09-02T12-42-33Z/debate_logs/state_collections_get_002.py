#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_get_002
# strategy: delete_consistency
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE consistency) on the DESCRIBE face
  (collections+get; runtime PATHS describe_collection =
   /collections/{name}, verbatim raw_knowledge api_endpoints[].url).
  The assertion's negative face: missing collection -> HTTP 404 WITH an
  error message, never 200 with config.
  (A negative never-created) describe a never-created unique name ->
      exactly 404 + error message in the body. A 200 with config here
      is the assertion's own Type1_IllegalSuccess ("never 200 with
      config"); any other status contradicts the pinned 404.
  (B setup positive) create the collection -> describe -> exactly 200
      (the positive face of the same assertion, G4 pairing).
  (C negative deleted) DELETE (confirmed 200) -> describe the deleted
      name -> exactly 404 + error message; a 200 with config = ghost
      state after a confirmed delete (Type1).
  (D stability) a second describe of the deleted name stays 404.
  Only collections created by this script are deleted; the
  never-created name is never touched by any mutating call.
  [chunk_collections+get coverage: delete_consistency x
   qdrant_behavioral_collections_get_001 (404-with-error-message face:
   never-created / deleted-ghost / double-read stability + 200
   positive control)]
Oracle: describe(never-created) = 404 with a non-empty error message;
  describe(existing) = 200; after a 200-confirmed DELETE,
  describe(deleted) = 404 with a non-empty error message twice in a
  row. Any 200-with-config on a non-existent name = Type1_
  IllegalSuccess; any non-404 status where 404 is pinned = Type4_
  StateLogicViolation; a 404 with an empty body (no error message)
  = Type4 (assertion requires the message); 5xx judged Type3 only
  after /healthz confirms liveness.
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
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def error_message_present(raw, name):
    """404 must carry an error message (assertion wording). Accept the
    JSON envelope's error string or a non-JSON body mentioning the name."""
    b = parse_json(raw)
    if isinstance(b, dict):
        err = b.get("error")
        if isinstance(err, str) and err.strip():
            return True, err
        # any other non-empty textual body mentioning the queried name
        if str(raw).strip() and name in str(raw):
            return True, str(raw)[:120]
        return False, str(raw)[:120]
    txt = str(raw or "").strip()
    if txt and name in txt:
        return True, txt[:120]
    return False, txt[:120]


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scg2_" + TS + "_"
    C = PFX + "ghost"
    NEVER = PFX + "never_created"
    DEFECTS = []

    def alive():
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def describe(name):
        try:
            return safe_request("GET", "describe_collection",
                                path_params={"name": name})
        except Exception as e:
            return -1, str(e)

    def judge_missing_leg(tag, name, expect_present=True):
        """Expected: exactly 404 + error message. Returns 'ERR' on
        script-level failure, else 'OK' (defects appended internally)."""
        s, raw = describe(name)
        print(f"[describe#{tag}] name={name} status={s} raw={str(raw)[:240]}")
        if s == 0:
            alive()
            return "ERR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"describe#{tag} returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "ERR"
            return "OK"
        if s == 200:
            DEFECTS.append(f"describe#{tag} returned 200 with a config for "
                           f"non-existent name {name!r} — the assertion pins "
                           f"'never 200 with config' — Type1_IllegalSuccess — "
                           f"raw={str(raw)[:150]} "
                           f"(qdrant_behavioral_collections_get_001)")
            return "OK"
        if s != 404:
            DEFECTS.append(f"describe#{tag} returned {s} for non-existent name "
                           f"(pinned: 404 with an error message) — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            return "OK"
        if expect_present:
            ok_msg, detail = error_message_present(raw, name)
            if not ok_msg:
                DEFECTS.append(f"describe#{tag} returned a bare 404 without an "
                               f"error message for {name!r} (assertion requires "
                               f"'404 with an error message') — "
                               f"Type4_StateLogicViolation — body={detail!r}")
        return "OK"

    try:
        # ---- (A) negative: never-created name ----
        if judge_missing_leg("A-never", NEVER) == "ERR":
            return "SCRIPT_ERROR"

        # ---- (B) setup + positive control: existing -> 200 ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_FAIL: create {err}")
            return "SCRIPT_ERROR"
        s, raw = describe(C)
        print(f"[describe#B-existing] status={s} raw={str(raw)[:200]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"describe on the existing collection returned "
                               f"{s} — Type3_RuntimeFailure — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s != 200:
            if alive():
                DEFECTS.append(f"describe on the just-created collection returned "
                               f"{s} (assertion pins 200 with full config) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"

        # ---- (C) negative: deleted name -> 404 + error message ----
        s, raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[delete] status={s} raw={str(raw)[:200]}")
        if s != 200:
            print(f"SETUP_FAIL: delete returned {s} (expected 200): {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        # brief poll: allow the confirmed delete to propagate to reads
        gone = False
        for _ in range(20):
            ds, draw = describe(C)
            if ds == 404:
                gone = True
                break
            time.sleep(0.5)
        print(f"[poll] describe(deleted) reached 404? {gone}")

        if judge_missing_leg("C-deleted", C) == "ERR":
            return "SCRIPT_ERROR"
        # ---- (D) stability: second read stays 404 ----
        if judge_missing_leg("D-repeat", C) == "ERR":
            return "SCRIPT_ERROR"

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
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
