#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_018
# strategy: no_residue_after_reject
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: no-residue-after-rejected-create on PUT /collections/{name}
  (collections+create; URL from raw_knowledge api_endpoints[].url). The
  behavioral assertion promises: an invalid vectors config (e.g. unknown
  distance enum) or malformed body is rejected with HTTP 400 (runtime
  observed: 'Format error in JSON body: data did not match any variant of
  untagged enum VectorsConfig' for distance:"Bogus"), never 200. The
  state-consistency angle: a rejected create must leave NO ghost
  collection — describe 404 and the name absent from list_collections.
  Legs: (N1) distance:"Bogus" -> expect 4xx, then ghost checks; (N2)
  BS-01 shape stress vectors:{} (empty object matches neither the dense
  branch — which requires vectors.size+vectors.distance per
  request_required_paths — nor a usable named map) -> conflict zone
  measured-only: 4xx => ghost checks, 200 => readback observation only
  (empty named map may be spec-legal, no defect claim); (P) positive
  control with a valid config -> 200 + describe 200 proving the residue
  probes are meaningful (G4 pairing).
  [chunk_collections+create-2of2 coverage: no_residue_after_reject x
   qdrant_behavioral_collections_create_003 (400 promise + ghost-state
   absence + measured-only vectors:{} face)]
Oracle: distance:"Bogus" -> 4xx (400 observed), never 200 (200 =
  Type1_IllegalSuccess); after any 4xx rejection describe must return 404
  and the name must be absent from list_collections (lingering state =
  Type4_StateLogicViolation ghost); 5xx on invalid input = Type3 only
  after /healthz confirms liveness; valid control create -> 200 with
  describe 200.
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

def ghost_checks(name, tag, defects):
    """After a rejected create: describe must 404 and the name must be
    absent from list_collections. Appends Type4 findings to defects."""
    gs, graw = safe_request("GET", "describe_collection", path_params={"name": name})
    print(f"[{tag} describe-after-reject] status={gs} raw={graw[:200]}")
    if gs != 404:
        defects.append(f"({tag}) create was rejected but describe returned {gs} "
                       f"(expected 404) — ghost collection state — "
                       f"Type4_StateLogicViolation")
    ls, lraw = safe_request("GET", "list_collections")
    present = (ls == 200 and name in (lraw or ""))
    print(f"[{tag} list-membership] status={ls} present={present}")
    if ls == 200 and present:
        defects.append(f"({tag}) rejected collection '{name}' still present in "
                       f"list_collections — stale list state — "
                       f"Type4_StateLogicViolation")
    elif ls != 200:
        print(f"OBSERVATION ({tag}): list_collections returned {ls}")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scc2d_" + TS + "_"
    C_N1 = PFX + "bogus"
    C_N2 = PFX + "empty"
    C_P = PFX + "ctrl"
    CREATED = [C_N1, C_N2, C_P]
    DEFECTS = []

    try:
        # ---- (N1) invalid distance enum -> must be 4xx, then no residue ----
        s1, raw1 = safe_request("PUT", "create_collection",
                                path_params={"name": C_N1},
                                body={"vectors": {"size": 4, "distance": "Bogus"}})
        print(f"[N1 create distance=Bogus] status={s1} raw={raw1[:300]}")
        if s1 == 0:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness N1-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                print("DEFECT: (N1) invalid-config create transport-failed and "
                      "/healthz is not 200 — service down on invalid input — "
                      "Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if 500 <= s1 <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness N1-5xx] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (N1) invalid distance enum returned {s1} with service "
                  f"alive — assertion promises HTTP 400 — Type3_RuntimeFailure — "
                  f"raw={raw1[:200]}")
            return "DEFECT_FOUND"
        if s1 in (200, 201):
            DEFECTS.append(f"(N1) invalid vectors config (distance:\"Bogus\") "
                           f"accepted with {s1} — assertion promises 400, never 200 — "
                           f"Type1_IllegalSuccess "
                           f"(qdrant_behavioral_collections_create_003)")
            gs, graw = safe_request("GET", "describe_collection",
                                    path_params={"name": C_N1})
            print(f"[N1 ghost-probe] describe status={gs} raw={graw[:200]}")
        elif s1 == 408:
            print("OBSERVATION (N1): 408 operation timeout — not a definitive "
                  "rejection; no ghost claim")
        elif 400 <= s1 <= 499:
            ghost_checks(C_N1, "N1", DEFECTS)
        else:
            print(f"OBSERVATION (N1): unexpected status {s1}; running ghost checks")
            ghost_checks(C_N1, "N1", DEFECTS)

        # ---- (N2) vectors:{} — BS-01 conflict zone, measured-only on 200 ----
        s2, raw2 = safe_request("PUT", "create_collection",
                                path_params={"name": C_N2}, body={"vectors": {}})
        print(f"[N2 create vectors={{}}] status={s2} raw={raw2[:300]}")
        if s2 == 0:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness N2-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                print("DEFECT: (N2) vectors:{} create transport-failed and "
                      "/healthz is not 200 — Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if 500 <= s2 <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness N2-5xx] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (N2) vectors:{{}} returned {s2} with service alive — "
                  f"Type3_RuntimeFailure — raw={raw2[:200]}")
            return "DEFECT_FOUND"
        if s2 in (200, 201):
            gs, graw = safe_request("GET", "describe_collection",
                                    path_params={"name": C_N2})
            print(f"[N2 readback] describe status={gs} raw={graw[:300]}")
            print("OBSERVATION (N2): vectors:{} accepted — empty named map may be "
                  "a spec-legal anyOf branch (request_required_paths "
                  "vectors.size/vectors.distance apply to the dense branch only); "
                  "measured-only, no defect claim")
        elif 400 <= s2 <= 499:
            ghost_checks(C_N2, "N2", DEFECTS)
        else:
            print(f"OBSERVATION (N2): unexpected status {s2}; running ghost checks")
            ghost_checks(C_N2, "N2", DEFECTS)

        # ---- (P) positive control: valid create must succeed and persist ----
        sp, rawp = safe_request("PUT", "create_collection",
                                path_params={"name": C_P},
                                body={"vectors": {"size": 4, "distance": "Euclid"}})
        print(f"[P control create] status={sp} raw={rawp[:200]}")
        if sp in (0,) or 500 <= sp <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness P-liveness] healthz status={_hs} raw={str(_hraw)[:120]}")
            print("SETUP_ERROR: control create failed — residue probes unverifiable")
            return "SCRIPT_ERROR"
        if sp not in (200, 201):
            DEFECTS.append(f"(P) valid control create rejected with {sp} — "
                           f"boundary closure of the same face — "
                           f"Type4_StateLogicViolation — raw={rawp[:200]}")
        else:
            gs, graw = safe_request("GET", "describe_collection",
                                    path_params={"name": C_P})
            print(f"[P control describe] status={gs} raw={graw[:200]}")
            if gs != 200:
                DEFECTS.append(f"(P) control create returned 200 but describe "
                               f"returned {gs} — created state absent — "
                               f"Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in CREATED:
            try:
                rt.drop_collection(n)
            except Exception:
                pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
