#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_get_004
# strategy: count_consistency
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: alias-resolution consistency of the DESCRIBE face
  (collections+get; runtime PATHS describe_collection =
   /collections/{name} + update_aliases / list_aliases, verbatim
   raw_knowledge api_endpoints[].url). The assertion's faces are
   name-resolution faces: an EXISTING (resolvable) name -> 200 with
   full config; an UNRESOLVABLE name -> 404, never 200 with config.
  Describe resolves aliases (proven this session), so the resolvable-
  name promise extends to alias names — attacked with two collections
  whose configs are DISTINGUISHABLE (dim 4 vs dim 8):
  (A setup/control) create A(dim4) and B(dim8); describe A directly
      -> 200 with params.vectors.size == 4 (readout extraction).
  (B positive via alias) create alias -> A; describe BY ALIAS -> 200
      with size == 4. A 404 on a live alias = the describe face fails
      to resolve a resolvable name (Type4); size == 8 = resolved to
      the WRONG target (Type4).
  (C switch) re-point the alias to B in ONE atomic update_aliases
      request (delete_alias + create_alias); describe BY ALIAS -> 200
      with size == 8 (stale size 4 = the readout did not follow the
      alias switch).
  (D integrity of originals) describe A and B DIRECTLY -> 200 with
      sizes 4 / 8 (switching must not disturb the originals).
  (E negative post-alias-delete) delete the alias; describe BY ALIAS
      -> exactly 404 with an error message (the name is no longer
      resolvable) — a 200-with-config = ghost alias (Type1); while A
      and B still answer 200 directly.
  [chunk_collections+get coverage: count_consistency(resolution
   readout) x qdrant_behavioral_collections_get_001 (alias-resolvable
   name -> 200 target config / unresolvable -> 404 / originals
   untouched)]
Oracle: describe by a live alias = 200 whose result.config.params.
  vectors.size equals the CURRENT alias target's created size (4
  before the switch, 8 after); 404 on a live alias, or a 200 naming
  the wrong target's size, = Type4_StateLogicViolation; after the
  alias is deleted describe by the alias name = exactly 404 with a
  non-empty error message (200-with-config = Type1_IllegalSuccess;
  bare 404 without message = Type4); A and B keep answering 200 with
  sizes 4 / 8 throughout; 5xx = Type3 only with /healthz liveness.
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


def vec_size(raw):
    """Extract result.config.params.vectors.size from a 200 describe body
    (response_shape: result.config.params.vectors = object)."""
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        return None
    cfg = res.get("config")
    par = cfg.get("params") if isinstance(cfg, dict) else None
    vec = par.get("vectors") if isinstance(par, dict) else None
    if isinstance(vec, dict):
        sz = vec.get("size")
        if isinstance(sz, int) and not isinstance(sz, bool):
            return sz
    return None


def error_message_present(raw, name):
    b = parse_json(raw)
    if isinstance(b, dict):
        err = b.get("error")
        if isinstance(err, str) and err.strip():
            return True
    return bool(str(raw or "").strip() and name in str(raw))


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scg4_" + TS + "_"
    A = PFX + "cola"      # dim 4
    B = PFX + "colb"      # dim 8
    AL = PFX + "al"
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

    def alias_actions(actions):
        return safe_request("POST", "update_aliases", {"actions": actions})

    def judge_size_leg(tag, name, expected_size, live_name):
        """Expected: 200 with params.vectors.size == expected_size.
        Returns 'ERR' on script-level failure, else 'OK'."""
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
        if s != 200:
            if alive():
                DEFECTS.append(f"describe#{tag} returned {s} for {live_name} "
                               f"(pinned: 200 with full config) — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]} "
                               f"(qdrant_behavioral_collections_get_001)")
            else:
                return "ERR"
            return "OK"
        sz = vec_size(raw)
        if sz is None:
            DEFECTS.append(f"describe#{tag} 200 body lacks a readable "
                           f"result.config.params.vectors.size — full-config "
                           f"shape violated — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:200]}")
        elif sz != expected_size:
            DEFECTS.append(f"describe#{tag} resolved to vectors.size={sz} but "
                           f"{expected_size} was pinned ({live_name}) — readout "
                           f"disagrees with the resolvable target — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:200]} "
                           f"(qdrant_behavioral_collections_get_001)")
        return "OK"

    try:
        # ---- (A) setup + direct-readout control ----
        ok, err = rt.setup_default(A, 4, "Cosine")
        if not ok:
            print(f"SETUP_FAIL: create A {err}")
            return "SCRIPT_ERROR"
        ok, err = rt.setup_default(B, 8, "Dot")
        if not ok:
            print(f"SETUP_FAIL: create B {err}")
            return "SCRIPT_ERROR"
        if judge_size_leg("A-direct", A, 4, "existing collection A") == "ERR":
            return "SCRIPT_ERROR"

        # ---- (B) positive: describe by live alias -> target's config ----
        s, raw = alias_actions([{"create_alias": {"alias": AL,
                                                  "collection_name": A}}])
        print(f"[alias create -> A] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: create_alias {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("GET", "list_aliases")
        print(f"[aliases control] status={s} raw={str(raw)[:300]}")
        if judge_size_leg("B-alias->A", AL, 4, "live alias on A") == "ERR":
            return "SCRIPT_ERROR"

        # ---- (C) atomic re-point in ONE request; describe follows the switch ----
        s, raw = alias_actions([
            {"delete_alias": {"alias": AL}},
            {"create_alias": {"alias": AL, "collection_name": B}},
        ])
        print(f"[alias switch -> B] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: alias switch {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        if judge_size_leg("C-alias->B", AL, 8, "switched alias on B") == "ERR":
            return "SCRIPT_ERROR"

        # ---- (D) originals untouched ----
        if judge_size_leg("D-A-direct", A, 4, "existing collection A") == "ERR":
            return "SCRIPT_ERROR"
        if judge_size_leg("D-B-direct", B, 8, "existing collection B") == "ERR":
            return "SCRIPT_ERROR"

        # ---- (E) negative: alias deleted -> unresolvable -> 404 ----
        s, raw = alias_actions([{"delete_alias": {"alias": AL}}])
        print(f"[alias delete] status={s} raw={str(raw)[:160]}")
        if s != 200:
            print(f"SETUP_FAIL: delete_alias {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("GET", "list_aliases")
        print(f"[aliases control after delete] status={s} raw={str(raw)[:300]}")
        s, raw = describe(AL)
        print(f"[describe#E-alias-deleted] name={AL} status={s} "
              f"raw={str(raw)[:240]}")
        if s == 0:
            alive()
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if alive():
                DEFECTS.append(f"describe of the deleted-alias name returned {s} "
                               f"with service alive — Type3_RuntimeFailure — "
                               f"raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif s == 200:
            DEFECTS.append(f"describe by deleted alias {AL!r} returned 200 with "
                           f"a config — the name is no longer resolvable; "
                           f"assertion pins 'never 200 with config' — "
                           f"Type1_IllegalSuccess — raw={str(raw)[:150]} "
                           f"(qdrant_behavioral_collections_get_001)")
        elif s != 404:
            if alive():
                DEFECTS.append(f"describe by deleted alias returned {s} (pinned: "
                               f"404 with an error message) — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]}")
            else:
                return "SCRIPT_ERROR"
        elif not error_message_present(raw, AL):
            DEFECTS.append("describe by deleted alias returned a bare 404 "
                           "without an error message (assertion requires the "
                           "message) — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
        # originals must STILL answer 200 after the alias delete
        if judge_size_leg("E-A-direct", A, 4, "existing collection A") == "ERR":
            return "SCRIPT_ERROR"
        if judge_size_leg("E-B-direct", B, 8, "existing collection B") == "ERR":
            return "SCRIPT_ERROR"

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            alias_actions([{"delete_alias": {"alias": AL}}])
        except Exception:
            pass
        try:
            rt.drop_collection(A)
        except Exception:
            pass
        try:
            rt.drop_collection(B)
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
