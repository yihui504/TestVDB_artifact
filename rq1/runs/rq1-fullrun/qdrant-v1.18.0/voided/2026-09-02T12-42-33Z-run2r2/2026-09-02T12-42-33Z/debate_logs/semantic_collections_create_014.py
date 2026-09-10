#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_014
# strategy: behavioral_contract
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_005
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 (WAL minima closure) + BS-02 (refusal diagnostics for
#   just-below values)
"""
Attack: behavioral_contract + diagnosis_quality x
  qdrant_range_collections_create_005 (chunk_collections+create-1of2;
  PUT /collections/{name}, path_key create_collection from runtime PATHS,
  URL from raw_knowledge api_endpoints[collections+create].url). The
  assertion (evidence_tier=explicit): wal_config at create takes the
  WalConfigDiff schema - wal_capacity_mb minimum 1 (resolved default 32),
  wal_segments_ahead minimum 0, wal_retain_closed minimum 0 (resolved
  default 1). G4 both-direction pairing on one setup:
    - closure: wal_config {wal_capacity_mb: 1, wal_segments_ahead: 0,
      wal_retain_closed: 0} -> 200 + describe readback
      result.config.wal_config (response_shape: wal_capacity_mb/wal_
      segments_ahead/wal_retain_closed integer) echoing the
      default-distinguishable fields (capacity 1 vs default 32;
      retain_closed 0 vs default 1; segments_ahead 0 equals the default and
      is recorded only)
    - violations (fresh names): wal_capacity_mb=0, wal_segments_ahead=-1,
      wal_retain_closed=-1 -> each refused 400/422, rubric-scored
  [chunk_collections+create-1of2 coverage: behavioral_contract x
   qdrant_range_collections_create_005 (all-minima closure + echoes) +
   diagnosis_quality x qdrant_range_collections_create_005 (3 violation
   refusals + rubric)]
Oracle: the all-minima wal_config create returns 200 result=true (any 4xx =
  Type1_IllegalRejection; 5xx with /healthz alive = Type3) and describe
  echoes wal_config.wal_capacity_mb == 1 and wal_config.wal_retain_closed ==
  0 (mismatch = Type4); wal_capacity_mb=0, wal_segments_ahead=-1 and
  wal_retain_closed=-1 are each refused 400/422 (any 2xx =
  Type1_IllegalSuccess) with no refusal scoring 0/3 on the Type-2 rubric
  (0/3 = Type2_PoorDiagnostics) - constraint
  qdrant_range_collections_create_005.

Rationale (G4/G7): a single script carries the closure and the three
violation directions with the shared dense setup, so an off-by-one in any
WAL bound surfaces without a second deployment round; echoes are only
claimed where distinguishable from resolved defaults per the response_shape.
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

PREFIX = "scc14_"
RUN = str(int(time.time()))
CREATED = []
DENSE = {"size": 4, "distance": "Cosine"}


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


def create(name, wal):
    st, raw = safe_request("PUT", "create_collection",
                           {"vectors": DENSE, "wal_config": wal},
                           path_params={"name": name})
    print(f"[create {name}] status={st} raw={str(raw)[:300]}")
    if st in (200, 201):
        CREATED.append(name)
    return st, raw


def describe_wal(name):
    st, raw = safe_request("GET", "describe_collection", path_params={"name": name})
    print(f"[describe {name}] status={st} raw={str(raw)[:300]}")
    if st != 200:
        script_error(f"describe of freshly created {name} returned {st}; readback unavailable")
    b = jload(raw)
    res = b.get("result") if isinstance(b, dict) else None
    if not isinstance(res, dict):
        script_error(f"describe of {name} returned no result object: raw={str(raw)[:200]}")
    cfg = res.get("config")
    if not isinstance(cfg, dict):
        script_error(f"describe of {name} returned no config object: raw={str(raw)[:200]}")
    wal = cfg.get("wal_config")
    if not isinstance(wal, dict):
        script_error(f"describe of {name} returned no config.wal_config object "
                     f"(response_shape declares result.config.wal_config with "
                     f"wal_capacity_mb/wal_segments_ahead/wal_retain_closed): "
                     f"raw={str(raw)[:200]}")
    return wal


def check_error_quality(raw, expected_param):
    """Type-2 rubric: parameter_named + format_hint + actionable."""
    body = jload(raw) if isinstance(raw, str) else raw
    error_msg = json.dumps(body).lower() if isinstance(body, dict) else str(body).lower()
    score = 0
    criteria = []
    if expected_param.lower() in error_msg:
        score += 1
        criteria.append("param_named")
    format_hints = ["must be", "expected", "should be", "valid", "range", "type",
                    "at least", "minimum", "greater", "non-negative", "positive"]
    hit = [h for h in format_hints if h in error_msg]
    if hit:
        score += 1
        criteria.append(f"format_hint({hit[0]})")
    action_hints = ["correct", "try", "use", "change", "specify", "provide"]
    hit2 = [h for h in action_hints if h in error_msg]
    if hit2:
        score += 1
        criteria.append(f"actionable({hit2[0]})")
    return score, criteria, error_msg


def guard(st, raw, tag):
    """Common status guard: transport/5xx handling."""
    if st == 0:
        liveness("transport")
        script_error(f"transport failure on {tag}; no defect conclusion")
    if 500 <= st <= 599:
        if liveness("5xx") != 200:
            script_error(f"{tag} 5xx ({st}) and /healthz not 200; deployment unstable")
        defect("Type3_RuntimeFailure",
               f"[{tag}] server error {st} while /healthz is alive; raw={str(raw)[:200]}")


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
        ok, err = rt.setup_default(mkn("ctl"), 4, "Cosine")
        if not ok:
            script_error(f"control setup_default failed: {err}")
        print("[control] setup_default create OK (deployment healthy)")
        try:
            rt.drop_collection(mkn("ctl"))
        except Exception:
            pass

        # ---- closure: all WAL minima at once ----
        minima = {"wal_capacity_mb": 1, "wal_segments_ahead": 0,
                  "wal_retain_closed": 0}
        name = mkn("ok_minima")
        st, raw = create(name, minima)
        guard(st, raw, "wal minima closure")
        if st != 200:
            defect("Type1_IllegalRejection",
                   f"[wal minima closure] wal_config at the exact inclusive minima "
                   f"{minima} was refused with {st}; constraint "
                   f"qdrant_range_collections_create_005 declares "
                   f"wal_capacity_mb>=1, wal_segments_ahead>=0, "
                   f"wal_retain_closed>=0 - minima are inclusive; "
                   f"raw={str(raw)[:250]}")
        b = jload(raw)
        if not isinstance(b, dict) or b.get("result") is not True:
            defect("Type4_StateLogicViolation",
                   f"[wal minima closure] 200 body must carry result=true "
                   f"(response_shape result:boolean); raw={str(raw)[:250]}")
        wal = describe_wal(name)
        print(f"[wal minima closure] persisted wal_config = {wal!r}")
        for field, expected, note in [
            ("wal_capacity_mb", 1, "distinguishable from default 32"),
            ("wal_retain_closed", 0, "distinguishable from default 1"),
        ]:
            got = wal.get(field)
            if got != expected:
                defect("Type4_StateLogicViolation",
                       f"[wal minima closure] expected result.config.wal_config."
                       f"{field} == {expected} ({note}), got {got!r} (expected vs "
                       f"actual mismatch); wal_config={wal!r}")
            print(f"[wal minima closure] wal_config.{field} echo == {expected} (OK)")
        print(f"[wal minima closure] wal_config.wal_segments_ahead echo = "
              f"{wal.get('wal_segments_ahead')!r} (0 equals the resolved default; "
              f"recorded)")

        # ---- violations: each must be refused + rubric-scored ----
        cases = [
            ("cap0", "wal_capacity_mb", 0,
             "wal_capacity_mb=0 (minimum 1)"),
            ("ahead_neg", "wal_segments_ahead", -1,
             "wal_segments_ahead=-1 (minimum 0)"),
            ("retain_neg", "wal_retain_closed", -1,
             "wal_retain_closed=-1 (minimum 0)"),
        ]
        for tag, field, value, why in cases:
            name = mkn(f"bad_{tag}")
            st, raw = create(name, {field: value})
            guard(st, raw, tag)
            if 200 <= st <= 299:
                defect("Type1_IllegalSuccess",
                       f"[{tag}] wal_config.{why} was ACCEPTED with status {st}; "
                       f"constraint qdrant_range_collections_create_005 fixes the "
                       f"minimum; raw={str(raw)[:250]}")
            if st not in (400, 422):
                script_error(f"[{tag}] unadjudicable refusal status {st} "
                             f"(expected 400/422); raw={str(raw)[:200]}")
            score, criteria, msg = check_error_quality(raw, field)
            print(f"[{tag}] refused with {st}; rubric score={score}/3 "
                  f"criteria={criteria}; message={msg[:250]}")
            if score == 0:
                defect("Type2_PoorDiagnostics",
                       f"[{tag}] the refusal for wal_config.{why} names no "
                       f"parameter, gives no range hint and no actionable "
                       f"suggestion (0/3 on the Type-2 rubric); message={msg[:250]}")

        print("[summary] WAL minima closure accepted with exact echoes; the three "
              "violations refused with rubric-carrying diagnostics - WAL bounds "
              "hold per qdrant_range_collections_create_005")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
