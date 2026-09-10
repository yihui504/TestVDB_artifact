#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_007
# strategy: boundary (strategy 1)
# endpoint: collections+create
# constraint_ids: qdrant_range_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-04 Boundary Default Optimism (docs promise timeout minimum 1; a serde
#   integer with no validated minimum silently admits 0 is exactly this blindspot)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy1 boundary-value x qdrant_range_collections_create_001 on collections+create
  (PUT /collections/{collection_name}; chunk_collections+create-1of2 unit
  constraints::qdrant_range_collections_create_001, evidence_tier=explicit). The
  constraint's assertion, quoted verbatim:
    "timeout minimum 1 (seconds)"
  timeout is a QUERY parameter (openapi in:query) - it goes through query_params, never
  the body (v34 R1 lesson: body-stuffed query params are silently dropped and the probe
  never takes effect). Boundary matrix (G4 both directions, fresh collection per leg):
    negative (expect_rejected): ?timeout=0 (min-1), ?timeout=-1;
    positive (judge_200): ?timeout=1 (min closure), ?timeout=60 (documented default
      scale for sibling endpoints' timeout; a mid-range sentinel).
  No documented maximum exists in either source -> max legs N/A (annotated, not
  fabricated).
[chunk_collections+create-1of2 coverage: strategy1 x qdrant_range_collections_create_001
  (this script); siblings 008..012 cover strategy1 x range_002.._006; 001..006 cover
  strategy2 x type_001.._006]
Oracle: ?timeout=0 and ?timeout=-1 -> 4xx each (2xx = Type1_IllegalSuccess: below-
  minimum timeout accepted, violating "timeout minimum 1"); ?timeout=1 and ?timeout=60
  -> 2xx each with envelope result:boolean=true (4xx on the min-closure leg = Type4
  disposition conflict: documented-legal value rejected); 5xx with /healthz alive or
  dead-after-3-probes = Type3; transport failure with healthy /healthz = SCRIPT_ERROR.
Constraint: qdrant_range_collections_create_001
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
declares the PUT /collections/{collection_name} timeout parameter {in: query, integer,
minimum: 1} - the contract grid IS corroborated by the published spec (no phantom
grid). Response grid {status:string, time:number, result:boolean}.
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

PFX = "bcc07" + uuid.uuid4().hex[:6]
CREATED = []
DIM = 4
DENSE = {"size": DIM, "distance": "Cosine"}
ASSERT = "timeout minimum 1 (seconds)"


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


def create(name, timeout_value):
    # timeout is a QUERY param (openapi in:query) - forwarded via query_params exactly
    return safe_request("PUT", "create_collection", body={"vectors": DENSE},
                        path_params={"name": name},
                        query_params={"timeout": timeout_value}, timeout=90)


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


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[constraint quote] {ASSERT}")
    print("[matrix note] no documented maximum in any source -> max-closure legs N/A (annotated)")
    findings = []
    legs = [
        ("timeout=0 (min-1)", 0, "4xx"),
        ("timeout=-1", -1, "4xx"),
        ("timeout=1 (min closure)", 1, "2xx"),
        ("timeout=60 (mid-range sentinel)", 60, "2xx"),
    ]
    try:
        for label, tv, expected in legs:
            name = PFX + "l" + str(len(CREATED))
            CREATED.append(name)
            st, raw = create(name, tv)
            print(f"[{label}] status={st} raw={str(raw)[:300]}")
            if not transport_gate(label, st, raw, findings):
                break
            if expected == "4xx":
                v = rt.expect_rejected(st, raw, setup_ok=True)
                if v == "DEFECT_FOUND":
                    findings.append((0, f"Type1_IllegalSuccess: '{label}' ACCEPTED with {st} - "
                                        f"constraint asserts 'timeout minimum 1'; below-minimum "
                                        f"must be rejected; raw: {str(raw)[:200]}"))
                elif v == "NO_DEFECT":
                    print(f"[conform] '{label}' rejected with {st}")
                else:
                    findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st}"))
            else:
                v = rt.judge_200(st, raw, setup_ok=True)
                if v == "DEFECT_FOUND":
                    findings.append((2, f"Type4 disposition conflict: '{label}' documented-legal "
                                        f"timeout rejected with {st}; raw: {str(raw)[:200]}"))
                    continue
                try:
                    env = json.loads(raw) if raw else {}
                    ok_env = isinstance(env.get("result"), bool) and env["result"]
                except Exception:
                    ok_env = False
                if ok_env:
                    print(f"[conform] '{label}' 2xx with result:boolean=true envelope")
                else:
                    findings.append((2, f"Type4_StateLogicViolation: '{label}' 2xx but envelope "
                                        f"violates result:boolean=true grid; raw: {str(raw)[:200]}"))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: below-minimum timeouts rejected; min closure + sentinel accepted")
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
