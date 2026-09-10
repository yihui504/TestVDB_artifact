#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_update_003
# strategy: count_consistency
# endpoint: collections+update
# constraint_ids: qdrant_range_collections_update_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/update-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: boundary closure + rejection of the update-time HnswConfigDiff
  schema minima on PATCH collections+update (runtime PATHS
  update_collection + create_collection + describe_collection,
  verbatim raw_knowledge api_endpoints[].url).
  qdrant_range_collections_update_001 pins: m >= 0, ef_construct >= 4,
  full_scan_threshold >= 10 (KB, the diff-specific minimum),
  payload_m >= 0. G4 closure: the inclusive minima themselves must be
  accepted AND persisted (describe echo; R16 lesson: 200-without-echo
  = silent-ignore defect family). G6 rationale for the negative
  mutation point: config-level minima are validated when the diff is
  applied; a below-min diff that is 200-accepted poisons later
  optimizer runs (HNSW with ef_construct 3 / negative payload_m), so
  rejection at update time is the invariant that keeps the collection
  healthy. Legs (each on a fresh empty collection so no leg's residue
  can contaminate another):
  (A1) index-shape minima closure: PATCH hnsw_config {m: 0,
       ef_construct: 4} -> 200; describe echo m == 0 AND
       ef_construct == 4.
  (A2) scan minima closure: PATCH hnsw_config {full_scan_threshold:
       10, payload_m: 0} -> 200; describe echo full_scan_threshold
       == 10 AND payload_m == 0 (payload_m echoes only when set;
       baseline describe recorded whether the key materializes).
  (B1..B4) below-min negatives, one per value: m=-1 / ef_construct=3
       / full_scan_threshold=9 / payload_m=-1 -> 400/422 expected
       AND describe readback still shows the pre-PATCH defaults
       (unchanged, no ghost residue). A 2xx on any of them =
       Type1_IllegalSuccess (out-of-bound diff accepted); a 2xx that
       additionally ECHOES the illegal value = applied out-of-bound
       config (stronger Type1). A rejection that leaves changed state
       = Type4_StateLogicViolation.
  [chunk_collections+update coverage: count_consistency (boundary
   closure readback) x qdrant_range_collections_update_001]
Oracle: inclusive-minima PATCH (m=0, ef_construct=4, full_scan_threshold=10, payload_m=0) returns HTTP 200 with describe echo;
  each below-min PATCH (m=-1, ef_construct=3, full_scan_threshold=9, payload_m=-1) on a live collection -> 400/422
  with describe readback unchanged; each below-min
  PATCH (m=-1, ef_construct=3, full_scan_threshold=9, payload_m=-1)
  -> 400/422 with the describe readback unchanged — 2xx on a
  below-min diff = Type1_IllegalSuccess, 2xx-without-echo on a
  closure value or changed state after a rejection =
  Type4_StateLogicViolation; 5xx = Type3 only with /healthz liveness.
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

DIM = 4


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


def get_hnsw(raw):
    b = parse_json(raw)
    res = b.get("result") if isinstance(b, dict) else None
    cfg = res.get("config") if isinstance(res, dict) else None
    hn = cfg.get("hnsw_config") if isinstance(cfg, dict) else None
    return hn if isinstance(hn, dict) else None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scup3_" + TS + "_"
    DEFECTS = []
    names = []

    CLOSURE_LEGS = [
        ("A1_index_m_ef", {"m": 0, "ef_construct": 4},
         {"m": 0, "ef_construct": 4}),
        ("A2_scan_fst_pm", {"full_scan_threshold": 10, "payload_m": 0},
         {"full_scan_threshold": 10, "payload_m": 0}),
    ]
    NEG_LEGS = [
        ("B1_m_neg", {"m": -1}),
        ("B2_ef_neg", {"ef_construct": 3}),
        ("B3_fst_neg", {"full_scan_threshold": 9}),
        ("B4_pm_neg", {"payload_m": -1}),
    ]

    def alive():
        hs, hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
        return hs == 200

    def describe_hn(tag, name):
        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": name})
        print(f"[describe {tag}] status={s} raw={str(raw)[:240]}")
        if s == 0:
            if not alive():
                return None, "TRANSPORT"
            DEFECTS.append(f"describe({tag}) transport failure with /healthz "
                           f"alive — Type3_RuntimeFailure")
            return None, "ERR"
        if 500 <= s <= 599:
            if not alive():
                return None, "TRANSPORT"
            DEFECTS.append(f"describe({tag}) returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return None, "ERR"
        if s != 200:
            DEFECTS.append(f"describe({tag}) on the existing collection "
                           f"returned {s} — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]}")
            return None, "ERR"
        return get_hnsw(raw), "OK"

    try:
        for tag, want in CLOSURE_LEGS:
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection",
                                  {"vectors": {"size": DIM, "distance": "Cosine"}},
                                  path_params={"name": name})
            print(f"[{tag} create] status={s} raw={str(raw)[:160]}")
            if s != 200:
                print(f"SETUP_FAIL: create {tag} {s} {str(raw)[:200]}")
                return "SCRIPT_ERROR"
            hn0, st0 = describe_hn(tag + "_base", name)
            if st0 == "TRANSPORT":
                return "SCRIPT_ERROR"
            s, raw = safe_request("PATCH", "update_collection",
                                  {"hnsw_config": dict(want)},
                                  path_params={"name": name})
            print(f"[{tag} patch {json.dumps(want)}] status={s} "
                  f"raw={str(raw)[:200]}")
            if s == 0:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"{tag} transport failure with /healthz alive — "
                               f"Type3_RuntimeFailure")
                continue
            if 500 <= s <= 599:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"{tag} returned {s} with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
                continue
            if s != 200:
                DEFECTS.append(f"{tag} in-bound minimum hnsw diff "
                               f"{json.dumps(want)} rejected with {s} — "
                               f"boundary closure violated — "
                               f"Type1_IllegalSuccess — raw={str(raw)[:150]}")
                continue
            hn1, st1 = describe_hn(tag + "_post", name)
            if st1 == "TRANSPORT":
                return "SCRIPT_ERROR"
            if hn1 is not None:
                for k, wv in want.items():
                    got = hn1.get(k)
                    if got is None and not (isinstance(hn0, dict)
                                            and k not in hn0):
                        # key present pre-PATCH but dropped now = anomaly
                        DEFECTS.append(f"{tag} 200 but describe dropped "
                                       f"hnsw_config.{k} (pre-PATCH it "
                                       f"materialized) — "
                                       f"Type4_StateLogicViolation")
                        continue
                    if got != wv:
                        DEFECTS.append(f"{tag} 200 but describe "
                                       f"hnsw_config.{k}={got!r} (wanted {wv}) "
                                       f"— 200-without-echo silent ignore — "
                                       f"Type4_StateLogicViolation")

        for tag, over in NEG_LEGS:
            name = PFX + tag
            names.append(name)
            s, raw = safe_request("PUT", "create_collection",
                                  {"vectors": {"size": DIM, "distance": "Cosine"}},
                                  path_params={"name": name})
            print(f"[{tag} create] status={s} raw={str(raw)[:160]}")
            if s != 200:
                print(f"SETUP_FAIL: create {tag} {s} {str(raw)[:200]}")
                return "SCRIPT_ERROR"
            hn0, st0 = describe_hn(tag + "_base", name)
            if st0 == "TRANSPORT":
                return "SCRIPT_ERROR"
            s, raw = safe_request("PATCH", "update_collection",
                                  {"hnsw_config": dict(over)},
                                  path_params={"name": name})
            print(f"[{tag} patch {json.dumps(over)}] status={s} "
                  f"raw={str(raw)[:200]}")
            if s == 0:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"{tag} transport failure with /healthz alive — "
                               f"Type3_RuntimeFailure")
                continue
            if 500 <= s <= 599:
                if not alive():
                    return "SCRIPT_ERROR"
                DEFECTS.append(f"{tag} returned {s} (400/422 expected) with "
                               f"service alive — Type3_RuntimeFailure — "
                               f"raw={str(raw)[:150]}")
                continue
            if 200 <= s < 300:
                # accepted out-of-bound diff
                detail = f"raw={str(raw)[:150]}"
                hn1, st1 = describe_hn(tag + "_post", name)
                if st1 == "TRANSPORT":
                    return "SCRIPT_ERROR"
                if hn1 is not None:
                    k = list(over)[0]
                    got = hn1.get(k)
                    if got == over[k]:
                        detail = (f"AND describe echoes the illegal value "
                                  f"{k}={got!r} (applied out-of-bound "
                                  f"config)")
                DEFECTS.append(f"{tag} below-minimum hnsw diff "
                               f"{json.dumps(over)} ACCEPTED with {s} — "
                               f"Type1_IllegalSuccess — {detail}")
            elif s not in (400, 422):
                DEFECTS.append(f"{tag} rejection status {s} outside 400/422 — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(raw)[:150]}")
            else:
                # correct rejection; state must be unchanged
                hn1, st1 = describe_hn(tag + "_post", name)
                if st1 == "TRANSPORT":
                    return "SCRIPT_ERROR"
                if hn1 is not None and hn0 is not None:
                    for k in hn0:
                        if k in ("max_indexing_threads", "on_disk"):
                            continue
                        if hn1.get(k) != hn0[k]:
                            DEFECTS.append(f"{tag} rejected diff left state "
                                           f"change: hnsw_config.{k} "
                                           f"{hn0[k]!r} -> {hn1.get(k)!r} — "
                                           f"ghost residue — "
                                           f"Type4_StateLogicViolation")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        for n in names:
            try:
                rt.drop_collection(n)
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
