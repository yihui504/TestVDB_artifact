#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_011
# strategy: boundary (strategy 1)
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_005
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (WAL segment sizing below minimum
#   accepted silently corrupts durability tuning expectations)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_range_collections_create_005 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_range_collections_create_005, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "wal_config (create, WalConfigDiff schema): wal_capacity_mb minimum 1;
     wal_segments_ahead minimum 0; wal_retain_closed minimum 0"
  Legs (G4 both directions, fresh collection per leg):
    HARD negative (Pattern B' judge_schema_attack): wal_config.wal_capacity_mb=0
      (min-1; both grids say min 1), wal_config.wal_segments_ahead=-1 (min-1; both
      grids say min 0), wal_config.wal_retain_closed=-1 (illegal under BOTH the diff
      grid (min 0) and the resolved grid (min 1));
    HARD positive closure combo: {wal_capacity_mb: 1, wal_segments_ahead: 0} -> 200 +
      readback result.config.wal_config.wal_capacity_mb==1 (hard) and
      wal_segments_ahead==0 (hard);
    CONFLICT-ZONE measured-only (R8/R9 rule): wal_retain_closed=0 - legal per the
      create-side WalConfigDiff grid (minimum 0) but below the resolved describe-side
      WalConfig grid (minimum 1, default 1); disposition + readback printed for the
      judge, not adjudicated.
[chunk_collections+create-1of2 coverage: strategy1 x qdrant_range_collections_create_005
  (this script); siblings 007..010/012 cover range_001.._004/_006; 001..006 cover
  strategy2 x type_001.._006]
Oracle: wal_capacity_mb=0 / wal_segments_ahead=-1 / wal_retain_closed=-1 -> 4xx each
  (200 + persisted-as-sent = Type1_IllegalSuccess; coerced value = Type2-signal);
  {1,0} combo -> 200 result:true(boolean) + readbacks wal_capacity_mb==1 and
  wal_segments_ahead==0 (mismatch = Type4; documented-legal combo rejected = Type4
  disposition conflict); conflict leg wal_retain_closed=0 -> measured lines only (no
  defect claim on 2xx/4xx; 5xx with /healthz alive or dead-after-3-probes = Type3);
  transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_collections_create_005
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
WalConfigDiff (the create-side schema this constraint names) declares wal_capacity_mb
{minimum: 1}, wal_segments_ahead {minimum: 0}, wal_retain_closed {minimum: 0} - the
contract grid IS corroborated member-for-member. The resolved describe-side WalConfig
carries wal_capacity_mb {min 1}, wal_segments_ahead {min 0}, wal_retain_closed
{minimum: 1, default: 1} - the single-field asymmetry (retain_closed 0-vs-1) is
annotated and measured-only. Describe readback: result.config.wal_config.*.
"""
import os
import sys
import json
import time
import uuid
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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

PFX = "bcc11" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = ("wal_config (create, WalConfigDiff schema): wal_capacity_mb minimum 1; "
          "wal_segments_ahead minimum 0; wal_retain_closed minimum 0")
WPATH = ["config", "wal_config"]


def safe_request(method, path_key, **kw):
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz")
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def create(name, body):
    return safe_request("PUT", "create_collection", body=body,
                        path_params={"name": name}, timeout=60)


def describe_result(name):
    st, raw = safe_request("GET", "describe_collection",
                           path_params={"name": name}, timeout=30)
    if st != 200:
        return None, f"describe {st}: {str(raw)[:150]}"
    try:
        return json.loads(raw).get("result"), None
    except Exception as e:
        return None, f"envelope:{e}"


def walk(node, path):
    for k in path:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            return None
    return node


def transport_gate(label, st, raw, findings):
    if st <= 0:
        v = healthz_ladder(label)
        if v:
            findings.append((1, v))
        else:
            findings.append((3, f"SCRIPT-ERROR-transport: '{label}' failed with healthy /healthz: {str(raw)[:150]}"))
        return False
    if 500 <= st <= 599:
        v = healthz_ladder(label)
        findings.append((1, v if v else
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; body: {str(raw)[:200]}"))
        return False
    return True


def value_leg(label, body, field, attack_value, findings):
    path = WPATH + [field]
    name = PFX + "n" + str(len(CREATED))
    CREATED.append(name)
    st, raw = create(name, body)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_schema_attack(st, raw, name, path, attack_value, setup_ok=True)
    if v == "DEFECT_FOUND":
        res, err = describe_result(name)
        persisted = walk(res, path) if isinstance(res, dict) else None
        if persisted == attack_value:
            kind = "Type1_IllegalSuccess (persisted as-is)"
        else:
            kind = ("Type2-signal (readback differs from sent - silent clamp/normalize; "
                    "judge to adjudicate)")
        findings.append((0, f"{kind}: '{label}' accepted with {st}; sent={attack_value!r} "
                            f"persisted={persisted!r}; assertion: {ASSERT}"))
    elif v == "NO_DEFECT":
        if st in (200, 201):
            print(f"[conform*] '{label}' 200 but field dropped (lenient path)")
        else:
            print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    findings = []
    try:
        value_leg("wal_config.wal_capacity_mb=0 (min-1, both grids)",
                  {"vectors": DENSE, "wal_config": {"wal_capacity_mb": 0}},
                  "wal_capacity_mb", 0, findings)
        value_leg("wal_config.wal_segments_ahead=-1 (min-1, both grids)",
                  {"vectors": DENSE, "wal_config": {"wal_segments_ahead": -1}},
                  "wal_segments_ahead", -1, findings)
        value_leg("wal_config.wal_retain_closed=-1 (illegal under diff min 0 AND resolved min 1)",
                  {"vectors": DENSE, "wal_config": {"wal_retain_closed": -1}},
                  "wal_retain_closed", -1, findings)

        # HARD positive closure combo: both minima in one create
        name = PFX + "p0"
        CREATED.append(name)
        combo = {"wal_capacity_mb": 1, "wal_segments_ahead": 0}
        st, raw = create(name, {"vectors": DENSE, "wal_config": combo})
        print(f"[positive minima combo {json.dumps(combo)}] status={st} raw={str(raw)[:300]}")
        if transport_gate("positive wal minima combo", st, raw, findings):
            v = rt.judge_200(st, raw, setup_ok=True)
            if v == "DEFECT_FOUND":
                findings.append((2, f"Type4 disposition conflict: documented minima combo "
                                    f"{combo} rejected with {st}; raw: {str(raw)[:200]}"))
            else:
                try:
                    env = json.loads(raw) if raw else {}
                    ok_env = isinstance(env.get("result"), bool) and env["result"]
                except Exception:
                    ok_env = False
                if not ok_env:
                    findings.append((2, f"Type4_StateLogicViolation: 200 but envelope violates "
                                        f"result:boolean=true grid; raw: {str(raw)[:200]}"))
                else:
                    res, err = describe_result(name)
                    wc = walk(res, WPATH) if isinstance(res, dict) else None
                    print(f"[readback] config.wal_config={json.dumps(wc)[:200]}")
                    for f, sent in (("wal_capacity_mb", 1), ("wal_segments_ahead", 0)):
                        got = walk(res, WPATH + [f]) if isinstance(res, dict) else None
                        if got == sent:
                            print(f"[conform] wal_config.{f}={got!r} persisted (closure)")
                        else:
                            findings.append((2, f"Type4_StateLogicViolation: {f}={sent} accepted "
                                                f"but readback wal_config.{f}={got!r}"))

        # CONFLICT-ZONE measured-only leg
        name = PFX + "m0"
        CREATED.append(name)
        st, raw = create(name, {"vectors": DENSE, "wal_config": {"wal_retain_closed": 0}})
        print(f"[measured-only:wal_retain_closed=0 (diff min 0 vs resolved min 1)] status={st} raw={str(raw)[:300]}")
        if transport_gate("wal_retain_closed=0 conflict leg", st, raw, findings):
            res, err = describe_result(name) if st in (200, 201) else (None, "not-created")
            got = walk(res, WPATH + ["wal_retain_closed"]) if isinstance(res, dict) else None
            print(f"[measured-only:wal_retain_closed=0] input(diff) grid says min 0 (legal), "
                  f"resolved grid says min 1; disposition={st}; readback={got!r}; "
                  f"full wal_config={json.dumps(walk(res, WPATH) if isinstance(res, dict) else None)[:200]}")

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: hard wal minima enforced; {1,0} closure persisted; retain_closed=0 measured-only")
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    finally:
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


if __name__ == "__main__":
    main()
