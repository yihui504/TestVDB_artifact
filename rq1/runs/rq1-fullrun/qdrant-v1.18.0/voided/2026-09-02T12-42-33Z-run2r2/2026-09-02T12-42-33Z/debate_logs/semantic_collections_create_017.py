#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_017
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (a duplicate-name PUT silently succeeding would be a
#   create-as-update confusion - the REST verb must not mutate on conflict)
"""
Attack: behavioral_contract x qdrant_behavioral_collections_create_002
  (chunk_collections+create-2of2; PUT /collections/{name} via runtime
  path_key create_collection). The assertion (evidence_tier=explicit,
  defect_type_if_violated=Type1_IllegalSuccess): creating an existing
  collection name fails - 4xx family (409 observed on v1.18.0), never 200.
  Two legs: (1) duplicate with the IDENTICAL config; (2) duplicate with a
  DIFFERENT config (size 8 + hnsw_config diff) - the config difference must
  not turn the conflict into a silent reconfiguration. State closure: after
  both legs describe must still show the ORIGINAL config (size 4, distance
  Cosine, default m) - a mutated config = the rejected request had effects.
  [chunk_collections+create-2of2 coverage: behavioral_contract x
   qdrant_behavioral_collections_create_002 (dup same-config + dup
   different-config + original-config-intact closure)]
Oracle: second PUT on an existing name returns 4xx (409 observed family) in
  BOTH legs - any 200/201 = Type1_IllegalSuccess; 5xx with /healthz alive =
  Type3_RuntimeFailure; and the post-legs describe still returns 200 with
  result.config.params.vectors.size==4 / distance=='Cosine' - a changed
  config = Type4_StateLogicViolation (conflicting create mutated state) -
  constraint qdrant_behavioral_collections_create_002.

Rationale (G1/G4/G7): the promise's negative direction is the conflict
itself; the positive control is the first create (must 200). The
different-config leg is the destructive variant: if accepted it is not
merely a wrong status code, it is create-masked reconfiguration (state
corruption), hence the describe closure.
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

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p)
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

print("[path derivation] create_collection = /collections/{name} "
      "(raw_knowledge api_endpoints[collections+create].url = /collections/{collection_name})")

PREFIX = "scc017_"
RUN = str(int(time.time()))
CREATED = []


def safe_request(method, path_key, body=None, path_params=None, query_params=None, timeout=60):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
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


def mkn(tag):
    return f"{PREFIX}{RUN}_{tag}"


def classify_dup(tag, st, raw):
    """Adjudicate one duplicate-create leg. 4xx = correct rejection."""
    if st == 0:
        if liveness("transport") != 200:
            script_error(f"{tag}: transport failure and /healthz down; no defect conclusion")
        script_error(f"{tag}: transport failure; /healthz alive; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx") != 200:
            script_error(f"{tag}: 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"{tag}: duplicate-name create raised server error {st} while /healthz "
               f"is alive; raw={str(raw)[:200]}")
    if st in (200, 201):
        defect("Type1_IllegalSuccess",
               f"{tag}: PUT on an EXISTING collection name returned {st} - assertion "
               f"qdrant_behavioral_collections_create_002 declares 4xx (409 observed), "
               f"never 200; raw={str(raw)[:250]}")
    if 400 <= st <= 499:
        print(f"[{tag}] conflict correctly refused with {st}")
        return
    script_error(f"{tag}: unexpected status {st}; raw={str(raw)[:200]}")


def cleanup():
    for n in list(CREATED):
        try:
            rt.drop_collection(n)
        except Exception:
            pass


def main():
    hs, hraw = safe_request("GET", "healthz", timeout=15)
    print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")

    try:
        name = mkn("dup")
        first = {"vectors": {"size": 4, "distance": "Cosine"}}
        st, raw = safe_request("PUT", "create_collection", first,
                               path_params={"name": name})
        print(f"[create-original {name}] status={st} raw={str(raw)[:300]}")
        if st not in (200, 201):
            script_error(f"original create failed with {st}; setup for conflict test unavailable; raw={str(raw)[:200]}")
        CREATED.append(name)

        # leg 1: duplicate with identical config
        st1, raw1 = safe_request("PUT", "create_collection", first,
                                 path_params={"name": name})
        print(f"[dup-identical] status={st1} raw={str(raw1)[:300]}")
        classify_dup("dup-identical", st1, raw1)

        # leg 2: duplicate with a DIFFERENT config (size + hnsw diff)
        conflicting = {"vectors": {"size": 8, "distance": "Euclid"},
                       "hnsw_config": {"m": 32}}
        st2, raw2 = safe_request("PUT", "create_collection", conflicting,
                                 path_params={"name": name})
        print(f"[dup-different-config] status={st2} raw={str(raw2)[:300]}")
        classify_dup("dup-different-config", st2, raw2)

        # state closure: original config intact
        dst, draw = safe_request("GET", "describe_collection", path_params={"name": name})
        print(f"[describe {name}] status={dst} raw={str(draw)[:300]}")
        if dst != 200:
            if dst == 0:
                if liveness("transport") != 200:
                    script_error("transport failure on describe and /healthz down")
                script_error("transport failure on describe; /healthz alive")
            script_error(f"describe after conflict legs returned {dst}; raw={str(draw)[:200]}")
        d = jload(draw)
        dres = d.get("result") if isinstance(d, dict) else None
        params = ((dres or {}).get("config") or {}).get("params") if isinstance(dres, dict) else None
        vecs = params.get("vectors") if isinstance(params, dict) else None
        got_size = vecs.get("size") if isinstance(vecs, dict) else None
        got_dist = vecs.get("distance") if isinstance(vecs, dict) else None
        hnsw = ((dres or {}).get("config") or {}).get("hnsw_config") if isinstance(dres, dict) else None
        got_m = hnsw.get("m") if isinstance(hnsw, dict) else None
        print(f"[echo] persisted size={got_size!r} distance={got_dist!r} hnsw.m={got_m!r}")
        if got_size != 4 or got_dist != "Cosine":
            defect("Type4_StateLogicViolation",
                   f"after the duplicate-name legs the persisted config changed from the "
                   f"original (size=4, distance=Cosine) to size={got_size!r} "
                   f"distance={got_dist!r} - a conflicting create mutated existing state "
                   f"(expected vs actual mismatch)")
        if got_m not in (None, 16):
            defect("Type4_StateLogicViolation",
                   f"after the duplicate-name legs hnsw_config.m changed from default 16 "
                   f"to {got_m!r} - the conflicting hnsw_config of the refused create "
                   f"leaked into existing state")
        print("[summary] both duplicate-name creates refused in the 4xx family and the "
              "original config is intact - constraint "
              "qdrant_behavioral_collections_create_002 holds")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
