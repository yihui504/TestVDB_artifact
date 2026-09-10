#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_017
# strategy: create_duplicate_rejection
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_002
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Pattern B (duplicate creation) with state-preservation readback on
  PUT /collections/{name} (collections+create; URL from raw_knowledge
  api_endpoints[].url). The behavioral assertion promises: PUT of an
  already-existing collection name returns an error in the 4xx family
  (409 observed on v1.18.0), never 200. Sequence: (pre) describe -> 404
  proving a clean slate; (A) create {size:8, distance:"Euclid"} -> 200,
  upsert 2 points wait=true, count==2; (B) duplicate PUT of the SAME name
  with a DIFFERENT config {size:4, distance:"Dot"} -> must be 4xx; (C)
  after the rejected duplicate the original state must be intact:
  describe still reports vectors.size==8 / distance=="Euclid", the exact
  count is still 2, and the name appears exactly once in
  list_collections.
  [chunk_collections+create-2of2 coverage: create_duplicate_rejection x
   qdrant_behavioral_collections_create_002 (4xx promise + original-state
   preservation)]
Oracle: duplicate create of an existing name -> 4xx (409 observed family),
  never 200; after the 4xx the original config (size 8 / Euclid) and count 2
  are unchanged and the name occurs exactly once in the collections list.
  A 200 duplicate = Type1_IllegalSuccess (constraint's
  defect_type_if_violated) and, if the config was then overwritten to the
  duplicate's, additionally Type4_StateLogicViolation; a 5xx duplicate or
  any clobbered state after rejection = Type3/Type4 respectively (5xx
  judged Type3 only after /healthz confirms liveness).
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


def describe_vectors(name):
    """GET /collections/{name} -> (status, vectors_dict_or_None, raw)."""
    s, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    if s != 200:
        return s, None, raw
    b = parse_json(raw)
    cfg = ((b or {}).get("result") or {}).get("config") if b else None
    vec = (cfg or {}).get("params", {}).get("vectors") if isinstance(cfg, dict) else None
    return s, (vec if isinstance(vec, dict) else None), raw


def count_exact(name):
    s, raw = safe_request("POST", "count", path_params={"name": name},
                          body={"exact": True})
    if s != 200:
        return s, None, raw
    b = parse_json(raw)
    r = (b or {}).get("result") if b else None
    return s, (r.get("count") if isinstance(r, dict) else None), raw

def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scc2c_" + TS + "_"
    C = PFX + "dup"
    DEFECTS = []

    try:
        # ---- (pre) clean slate: the unique-prefixed name must not exist ----
        ps, praw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[pre describe] status={ps} raw={praw[:160]}")
        if ps == 200:
            print("SETUP_ERROR: unique-prefixed name already exists — environment not clean")
            return "SCRIPT_ERROR"

        # ---- (A) first create + data ----
        s, raw = safe_request("PUT", "create_collection", path_params={"name": C},
                              body={"vectors": {"size": 8, "distance": "Euclid"}})
        print(f"[A create] status={s} raw={raw[:200]}")
        if s == 0:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness A-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            return "SCRIPT_ERROR"
        if 500 <= s <= 599 or s not in (200, 201):
            print(f"SETUP_ERROR: first create returned {s} — cannot judge duplicate face")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [0.2] * 8} for i in range(2)]
        us, uraw = safe_request("PUT", "upsert_points", path_params={"name": C},
                                body={"points": pts}, query_params={"wait": "true"})
        print(f"[A upsert] status={us} raw={uraw[:160]}")
        if us not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {us} — cannot seed state")
            return "SCRIPT_ERROR"

        # ---- (B) duplicate create, same name, different config ----
        s2, raw2 = safe_request("PUT", "create_collection", path_params={"name": C},
                                body={"vectors": {"size": 4, "distance": "Dot"}})
        print(f"[B duplicate create] status={s2} raw={raw2[:300]}")
        if s2 == 0:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness B-transport] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                print("DEFECT: (B) duplicate create transport-failed and /healthz "
                      "is not 200 — service down — Type3_RuntimeFailure")
                return "DEFECT_FOUND"
            return "SCRIPT_ERROR"
        if 500 <= s2 <= 599:
            _hs, _hraw = safe_request("GET", "healthz", timeout=10)
            print(f"[liveness B-5xx] healthz status={_hs} raw={str(_hraw)[:120]}")
            if _hs != 200:
                return "SCRIPT_ERROR"
            print(f"DEFECT: (B) duplicate create returned {s2} with service alive — "
                  f"assertion promises a 4xx-family error — "
                  f"Type3_RuntimeFailure — raw={raw2[:200]}")
            return "DEFECT_FOUND"
        if s2 in (200, 201):
            DEFECTS.append(f"(B) duplicate create of existing name returned {s2} "
                           f"(assertion: 4xx family, 409 observed; never 200) — "
                           f"Type1_IllegalSuccess (qdrant_behavioral_collections_create_002)")
        # 3xx/other unexpected -> fall through to state check, record observation
        if s2 not in (400, 409, 422) and not (400 <= s2 <= 499):
            print(f"OBSERVATION (B): duplicate create returned unexpected status {s2}")

        # ---- (C) original state must be intact after the duplicate attempt ----
        vs, vec, vraw = describe_vectors(C)
        print(f"[C describe] status={vs} vectors={json.dumps(vec)[:200] if vec else vraw[:200]}")
        if vs != 200 or vec is None:
            print(f"SETUP_ERROR: describe returned {vs} after duplicate attempt")
            return "SCRIPT_ERROR"
        if vec.get("size") != 8:
            DEFECTS.append(f"(C) original config clobbered by duplicate attempt: "
                           f"vectors.size={vec.get('size')!r} (expected 8) — "
                           f"Type4_StateLogicViolation")
        if vec.get("distance") != "Euclid":
            DEFECTS.append(f"(C) original config clobbered by duplicate attempt: "
                           f"vectors.distance={vec.get('distance')!r} "
                           f"(expected 'Euclid') — Type4_StateLogicViolation")
        cs, cnt, craw = count_exact(C)
        print(f"[C count] status={cs} count={cnt} raw={craw[:160]}")
        if cs == 200 and cnt != 2:
            DEFECTS.append(f"(C) data lost after duplicate attempt: count exact="
                           f"{cnt!r} (expected 2) — Type4_StateLogicViolation "
                           f"(qdrant_inv_count_consistency_001)")
        ls, lraw = safe_request("GET", "list_collections")
        if ls == 200:
            occurrences = (lraw or "").count(C)
            print(f"[C list] status={ls} occurrences_of_name={occurrences}")
            if occurrences != 1:
                DEFECTS.append(f"(C) name occurs {occurrences}x in list_collections "
                               f"(expected exactly 1) — duplicated listing state — "
                               f"Type4_StateLogicViolation")
        else:
            print(f"OBSERVATION (C): list_collections returned {ls}")

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
