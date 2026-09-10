#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_exists_003
# strategy: upsert_idempotence
# endpoint: collections+exists
# constraint_ids: qdrant_behavioral_collections_exists_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/collection-exists
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: repeated-probe stability of the existence readout (Strategy 3
  adapted: idempotence of an identical read repeated against an
  unchanged state). collections+exists is the cheapest state poll
  clients use to wait out asynchronous lifecycle work (create/delete/
  recover/snapshot restore); the assertion pins EVERY answer to the
  same channel (200 + result.exists boolean, never 404). Repeated
  identical probes against a quiesced state must therefore be
  INDISTINGUISHABLE: same status, same shape, same verdict.
  A single divergent answer (flapping) breaks any polling loop built
  on this endpoint — e.g. a client that waits for exists=true after a
  restore would spin forever on one stray false.
  Rationale for the mutation point (G6): no mutation is needed between
  probes BY DESIGN — the attack is precisely that the server has no
  excuse to change its answer; any change is pure server-side state
  instability (the same class as readout flapping observed in
  lifecycle races), which is the destructive power being probed here.
  Legs:
  (A setup) create C -> 200 (setup gate).
  (B stability-present) 20 sequential exists probes -> every one
      exactly 200 + result.exists=true, boolean shape.
  (C transition) DELETE C -> 200.
  (D stability-absent) 20 sequential exists probes -> every one
      exactly 200 + result.exists=false, boolean shape — in
      particular not a single 404 (the assertion's "never").
  (E recreate + re-stabilize) recreate -> 20 probes -> all true.
  [chunk_collections+exists coverage: upsert_idempotence x
   qdrant_behavioral_collections_exists_001 (20x stable-present /
   20x stable-absent / 20x re-stabilized after recreate)]
Oracle: for a quiesced state every repeated exists probe returns
  200 + result.exists=<state> with a boolean result.exists; zero
  flaps (any probe answering 404/other non-200, a wrong verdict, or
  a shape violation = Type4_StateLogicViolation); 5xx =
  Type3_RuntimeFailure only after /healthz confirms liveness.
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

# exists endpoint is not in the runtime PATHS whitelist — register it
# VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "collections+exists", "method": "GET",
#    "url": "/collections/{collection_name}/exists"}
rt.PATHS["collection_exists"] = "/collections/{collection_name}/exists"
if rt.PATHS.get("collection_exists") != "/collections/{collection_name}/exists":
    print("VERDICT: SCRIPT_ERROR - exists URL registration failed")
    sys.exit(2)

N_PROBES = max(5, int(os.environ.get("TESTVDB_EXISTS_PROBES", "20")))


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_exists(raw):
    """Shape-checked readout per materialized response_shape
    (result: object, result.exists: boolean)."""
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return False, None, "non-JSON body"
    res = b.get("result") if isinstance(b, dict) else None
    if isinstance(res, bool):
        return False, res, "result is a bare bool (spec pins result.exists object shape)"
    if not isinstance(res, dict):
        return False, None, "result missing or not an object"
    ev = res.get("exists")
    if not isinstance(ev, bool):
        return False, None, "result.exists missing or not a boolean"
    return True, ev, ""


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sce3_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    def liveness(tag):
        print(f"[liveness {tag}] healthz probe required")
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def stability_run(tag, expect):
        """N sequential identical probes; every answer must equal the pinned
        channel+verdict. Returns True (done, defects may be recorded) or
        None (env-class abort)."""
        for i in range(N_PROBES):
            s, raw = safe_request("GET", "collection_exists",
                                  path_params={"collection_name": C})
            if s == 0:
                liveness(f"{tag}#{i}")
                return None
            if 500 <= s <= 599:
                if liveness(f"{tag}#{i}"):
                    DEFECTS.append(f"({tag}#{i}) exists returned {s} with service "
                                   f"alive — Type3_RuntimeFailure — raw={str(raw)[:150]}")
                    return True
                return None
            shape_ok, ev, note = parse_exists(raw)
            if s != 200:
                chan = "never 404" if s == 404 else "HTTP 200 expected"
                DEFECTS.append(f"({tag}#{i}) FLAP: exists returned {s} on probe {i+1}/"
                               f"{N_PROBES} of an unchanged state (assertion pins "
                               f"{chan}) — Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]} "
                               f"(qdrant_behavioral_collections_exists_001)")
                return True
            if not shape_ok:
                DEFECTS.append(f"({tag}#{i}) FLAP: exists 200 body violates pinned "
                               f"shape result.exists:boolean ({note}) — "
                               f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
                return True
            if ev != expect:
                DEFECTS.append(f"({tag}#{i}) FLAP: probe {i+1}/{N_PROBES} of an "
                               f"unchanged state answered exists={ev} (expected "
                               f"{expect}) — polling loop would mis-detect the "
                               f"state — Type4_StateLogicViolation "
                               f"(qdrant_behavioral_collections_exists_001)")
                return True
        print(f"[{tag}] OK: {N_PROBES}/{N_PROBES} identical answers "
              f"(200 + result.exists={expect})")
        return True

    try:
        # ---- (A setup) create ----
        a_s, a_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"[A create] status={a_s} raw={a_raw[:200]}")
        if a_s != 200:
            print(f"SETUP_ERROR: create returned {a_s}")
            return "SCRIPT_ERROR"

        # ---- (B) stability while present ----
        if stability_run("B stable-present", True) is None:
            return "SCRIPT_ERROR"

        # ---- (C) transition ----
        c_s, c_raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[C delete] status={c_s} raw={c_raw[:150]}")
        if c_s != 200:
            print(f"SETUP_ERROR: delete returned {c_s}")
            return "SCRIPT_ERROR"

        # ---- (D) stability while absent ----
        if stability_run("D stable-absent", False) is None:
            return "SCRIPT_ERROR"

        # ---- (E) recreate + re-stabilize ----
        e_s, e_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                  body={"vectors": {"size": 4, "distance": "Cosine"}})
        print(f"[E recreate] status={e_s} raw={e_raw[:150]}")
        if e_s != 200:
            print(f"SETUP_ERROR: recreate returned {e_s}")
            return "SCRIPT_ERROR"
        if stability_run("E re-stabilized", True) is None:
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
