#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: boundary_collections_create_016
# strategy: type + malformed-input (strategy 2 + strategy 7)
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 Parameter Type Coercion Trust (invalid enum / non-object / malformed
#   JSON vectors config accepted with 200 is the named blindspot manifestation)
"""
TestVDB Boundary Attack Script
Target: qdrant v1.18.0
Attack: type+malformed x qdrant_behavioral_collections_create_003 on collections+create (chunk_collections+create-2of2 unit assertions::qdrant_behavioral_collections_create_003)
Oracle: distance="Bogus" -> 4xx, and if 200 the persisted describe readback decides
  (persisted-as-sent = Type1_IllegalSuccess; silent-drop = lenient path, judge
  adjudicates) [Pattern B' judge_schema_attack per runtime protocol]; vectors=null /
  vectors=123 / truncated JSON body / trailing-comma JSON body -> 4xx each
  (200 = Type1_IllegalSuccess); 5xx with /healthz alive or /healthz death = Type3
  (a parser panic on malformed input is a crash, not a rejection); transport failure
  with healthy /healthz = SCRIPT_ERROR; positive control (valid Cosine create) must
  return 200 - proving the 4xx legs measure the malformed payloads, not a broken endpoint.
Unit detail: PUT /collections/{collection_name}; evidence_tier=explicit,
  defect_type_if_violated=Type1_IllegalSuccess. The assertion's expected_behavior,
  quoted verbatim:
    "invalid vectors config (e.g. unknown distance enum) or malformed JSON returns
     HTTP 400, not 200"

Legs (G4 positive control + four distinct malformation classes; distinct from R10's
  1of2 probes which used distance='Euclidean' alias / sub-field omission - here the
  assertion's own runtime-observed value and whole-stream malformations):
  distance="Bogus" (the exact non-enum value from the assertion's runtime observation);
  vectors=null (required field nulled - strategy 2 null);
  vectors=123 (object field as scalar - strategy 2 type confusion);
  body='{"vectors": {"size": 4, "distance"' (truncated JSON - strategy 7, sent as raw
    string so client-side serialization cannot pre-reject it);
  body='{"vectors": {"size": 4, "distance": "Cosine"},}' (trailing comma - strategy 7).
[chunk_collections+create-2of2 coverage: strategy6+1 x qdrant_resource_shard_number_001 =
  boundary_collections_create_013; envelope-positive x qdrant_behavioral_collections_create_001 =
  _014; duplicate-family x _002 = _015; enum/malformed x qdrant_behavioral_collections_create_003
  (this script); cosine-normalization x _004 = _017; timeout-query x _005 = _018;
  visibility chain x qdrant_bc_create_visibility_001 = _019]
Constraint: qdrant_behavioral_collections_create_003
source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
doc_version: 1.18.x (versioned v-1-18-x api-reference)

R8-lesson spec-grid cross-check (BEFORE oracle): the versioned v-1-18-x merged OpenAPI
(.sourcedeps local shard openapi.json) declares VectorsConfig as an untagged oneOf
{VectorParams | map<string,VectorParams>} - the assertion's runtime observation on this
binary family ('Format error in JSON body: data did not match any variant of untagged
enum VectorsConfig') is the documented 400 shape for these malformations. Raw-string
bodies ride the runtime's str-body pass-through (sent verbatim with JSON content-type),
so the DB's own serde boundary is what gets measured.
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

PFX = "bcc16" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
CREATED = []  # every attempted collection name; cleanup drops all (no list.remove)
DIM = 4
ASSERT = ("invalid vectors config (e.g. unknown distance enum) or malformed JSON "
          "returns HTTP 400, not 200")


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/path_params/
    query_params/timeout exactly - qdrant runtime protocol v2.3). A str body is sent
    verbatim (runtime str pass-through), which is how the malformed-JSON legs reach
    the server's own parser instead of being pre-rejected client-side."""
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
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive - malformed "
                         f"input must be a 4xx rejection, not a server error; body: {str(raw)[:200]}"))
        return False
    return True


def create(name, body):
    return safe_request("PUT", "create_collection", body=body,
                        path_params={"name": name}, timeout=60)


def new_name(tag):
    name = PFX + tag + str(len(CREATED))
    CREATED.append(name)
    return name


def enum_leg(findings):
    """Pattern B' (schema-class field illegal value): judge_schema_attack -
    expect_rejected forbidden per runtime protocol; verdict refined by printed
    sent-vs-persisted comparison."""
    label = 'distance="Bogus" (unknown enum member - assertion-observed value)'
    name = new_name("n")
    st, raw = create(name, {"vectors": {"size": DIM, "distance": "Bogus"}})
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_schema_attack(st, raw, name,
                               ["config", "params", "vectors", "distance"],
                               "Bogus", setup_ok=True)
    if v == "DEFECT_FOUND":
        # re-read for the printed sent-vs-persisted comparison (judge_schema_attack
        # already adjudicated; this print is the evidence trail)
        ds, draw = safe_request("GET", "describe_collection",
                                path_params={"name": name}, timeout=30)
        persisted = None
        try:
            res = json.loads(draw).get("result") if ds == 200 else None
            if isinstance(res, dict):
                node = res.get("config", {}).get("params", {}).get("vectors", {})
                persisted = node.get("distance") if isinstance(node, dict) else None
        except Exception:
            persisted = None
        findings.append((0, f"Type1_IllegalSuccess: '{label}' accepted with {st}; "
                            f"sent='Bogus' persisted={persisted!r}; assertion: {ASSERT}"))
    elif v == "NO_DEFECT":
        print(f"[conform] '{label}' rejected with {st} (or silent-dropped on a lenient "
              f"200 path - judge_schema_attack readback found no persisted 'Bogus')")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def form_leg(label, body, findings):
    """Pattern B (whole-request legality): null/scalar/malformed vectors config."""
    name = new_name("n")
    st, raw = create(name, body)
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.expect_rejected(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((0, f"Type1_IllegalSuccess: '{label}' ACCEPTED with {st} - "
                            f"assertion requires 400 for malformed vectors config / JSON; "
                            f"raw: {str(raw)[:200]}"))
    elif v == "NO_DEFECT":
        print(f"[conform] '{label}' rejected with {st}")
    else:
        findings.append((3, f"SCRIPT-ERROR: '{label}' judge={v} status={st} raw={str(raw)[:150]}"))


def positive_control(findings):
    """G4 pairing: a valid create must succeed on the same endpoint, proving the
    4xx legs measure the malformed payloads (not a broken deployment)."""
    label = "positive control (valid Cosine create)"
    name = new_name("p")
    st, raw = create(name, {"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"[{label}] status={st} raw={str(raw)[:300]}")
    if not transport_gate(label, st, raw, findings):
        return
    v = rt.judge_200(st, raw, setup_ok=True)
    if v == "DEFECT_FOUND":
        findings.append((2, f"Type4 disposition conflict: valid control create rejected "
                            f"with {st}; raw: {str(raw)[:200]}"))
    else:
        print(f"[conform] '{label}' accepted with {st}")


def main():
    print(f"ownership prefix: {PFX}")
    print(f"[assertion quote] {ASSERT}")
    findings = []
    try:
        positive_control(findings)
        enum_leg(findings)
        form_leg("vectors=null (required field nulled)", {"vectors": None}, findings)
        form_leg("vectors=123 (object field as scalar)", {"vectors": 123}, findings)
        form_leg("body truncated JSON", '{"vectors": {"size": 4, "distance"', findings)
        form_leg("body trailing comma",
                 '{"vectors": {"size": 4, "distance": "Cosine"},}', findings)

        if findings:
            findings.sort(key=lambda x: x[0])
            rank, msg = findings[0]
            if rank == 3:
                print(f"VERDICT: SCRIPT_ERROR - {msg}")
                sys.exit(2)
            print(f"VERDICT: DEFECT_FOUND ({msg})")
            sys.exit(1)
        print("OK: unknown distance enum, null/scalar vectors and malformed JSON bodies "
              "all rejected with 4xx; valid control accepted")
        print("VERDICT: NO_DEFECT")
        sys.exit(0)
    finally:
        # data-bearing create endpoint: these collections are ours - drop best-effort
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


if __name__ == "__main__":
    main()
