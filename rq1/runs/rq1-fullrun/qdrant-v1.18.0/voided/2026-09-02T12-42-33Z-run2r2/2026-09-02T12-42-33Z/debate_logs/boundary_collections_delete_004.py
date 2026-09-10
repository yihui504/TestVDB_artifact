#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_delete_004
# strategy: boundary (strategy4 special-value + strategy7 malformed-input on the path parameter)
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 Parameter Type Coercion Trust (assuming the router/serde
#   handles hostile name encodings; a panic or a silent 200-ok for a NUL-bearing
#   name is the named blindspot manifestation)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: strategy4+7 x qdrant_behavioral_collections_delete_001 on collections+delete (chunk_collections+delete unit assertions::qdrant_behavioral_collections_delete_001)
Oracle: DELETE /collections/{c} with never-created HOSTILE names (each carries
  this script's unique ownership prefix, so none can exist) -> 4xx only: 404
  (declared not-found) or 400/422 (invalid name encoding - legitimate rejection);
  any 2xx = Type1_IllegalSuccess (assertion: non-existent collection must give
  "404, not 200" - a 200 claims a phantom delete succeeded); any 5xx/panic with
  /healthz alive/dead = Type3_RuntimeFailure (strategy 7 defect signal: the DB
  must robustly 4xx hostile input, never crash); transport failure with healthy
  /healthz = SCRIPT_ERROR.
Hostile-name probes (all never-created; general JSON-over-HTTP dimensions, no
  DB-specific assumption):
  - NUL byte via percent-escape "%00" in the path segment (strategy 7);
  - unicode name incl. CJK + emoji (strategy 4);
  - overlong name: 1000 chars (strategy 4/7 length boundary);
  - SQL-injection metacharacters "'; DROP TABLE--" (strategy 4, handled-safely);
  - JSON-injection object fragment '{"$gt":""}' (strategy 4).
Delivery note: the %00 probe is pre-escaped in the path segment (urllib3 passes
  existing percent-escapes through verbatim), so the server - not the client -
  decodes it to a NUL byte. All probes go through the same safe_request ->
  rt.request single HTTP exit; requests percent-encodes unicode/metacharacters
  automatically, so what is measured is the server's router/serde face.
[chunk_collections+delete coverage: behavioral-positive x qdrant_behavioral_collections_delete_001
  = _001; behavioral-negative-404 x same assertion = _002; stateful double-delete
  x same assertion = _003; strategy4+7 malformed-names x same assertion (this
  script); invisibility-chain x qdrant_bc_delete_invisibility_001 = _005]
Constraint: qdrant_behavioral_collections_delete_001
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)
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

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
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

PFX = "bcd4" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
ASSERT = ("DELETE on an existing collection returns HTTP 200; DELETE on a "
          "non-existent collection returns 404, not 200")

# hostile never-created names (strategy 4 + 7 general dimensions)
HOSTILE_NAMES = [
    ("nul-percent00", PFX + "nul%00x"),            # NUL via percent-escape
    ("unicode-cjk-emoji", PFX + "uni中文测试🎯"),   # unicode boundary
    ("overlong-1000", PFX + "long" + "a" * 1000),  # length boundary
    ("sql-injection", PFX + "sq'; DROP TABLE--"),  # SQL metacharacters
    ("json-injection", PFX + "jsn{\"$gt\":\"\"}"),  # JSON object fragment
]


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/path_params/
    query_params/timeout exactly - qdrant runtime protocol v2.3)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: inline safe_request('GET','healthz') probes, 3 attempts
    2s apart. Returns a bare Type3 message if the service is down, else None."""
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz")
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def transport_gate(label, st, raw, findings):
    """Three-outcome isolation (G8): returns True if the leg is adjudicable,
    False after recording a transport/5xx finding."""
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
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; "
                         f"body: {str(raw)[:250]}"))
        return False
    return True


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    tried = []  # names probed (for defensive cleanup; no list.remove)
    try:
        for tag, name in HOSTILE_NAMES:
            tried.append(name)
            shown = name if len(name) <= 60 else name[:57] + "..."
            st, raw = safe_request("DELETE", "drop_collection",
                                   path_params={"name": name}, timeout=60)
            print(f"[{tag}] name={shown!r} status={st} raw={str(raw)[:300]}")
            label = f"delete hostile[{tag}]"
            if not transport_gate(label, st, raw, findings):
                continue
            # ---- assert: declare expectation first, then compare (D3a) ----
            if st == 404:
                print(f"[conform] {tag}: 404 (declared not-found for a non-existent "
                      f"collection)")
            elif st in (400, 422):
                print(f"[conform] {tag}: {st} (hostile name rejected at the "
                      f"validation face - robust handling)")
            elif 200 <= st <= 299:
                findings.append((0, f"Type1_IllegalSuccess: {tag} hostile never-"
                                    f"created name DELETE returned {st} - assertion "
                                    f"demands 404, not 200 (phantom delete success); "
                                    f"raw: {str(raw)[:200]}"))
            elif 400 <= st <= 499:
                print(f"[conform-with-note] {tag}: {st} (rejected, but not 404/400/422 "
                      f"- measured conflict zone, judge to weigh)")
            else:
                findings.append((3, f"SCRIPT-ERROR: {tag} unexpected status {st}: "
                                    f"{str(raw)[:150]}"))

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: all hostile never-created names got 4xx (404/400/422) on the "
              "delete face - no phantom 200, no 5xx/panic")
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    finally:
        # nothing was created; defensive best-effort drops are wrapped (hostile
        # names can never have existed, so these are no-ops in the conform case)
        for n in list(tried):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n[:40]}): {e}")


if __name__ == "__main__":
    main()
