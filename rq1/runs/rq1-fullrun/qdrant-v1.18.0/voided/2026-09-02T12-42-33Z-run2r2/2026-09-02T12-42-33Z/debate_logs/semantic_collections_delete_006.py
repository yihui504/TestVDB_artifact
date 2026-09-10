#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_delete_006
# strategy: type_coercion
# endpoint: collections+delete
# constraint_ids: qdrant_behavioral_collections_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - the team assumes the REST
#   framework validates query params; the versioned v-1-18-x OpenAPI declares
#   timeout as integer minimum 1, and a silently-swallowed malformed or
#   below-minimum value is exactly the BS-01 "accepted with 200 OK" shape)
"""
Attack: type_coercion (Type1) x qdrant_behavioral_collections_delete_001 on
  collections+delete (chunk_collections+delete unit
  assertions::qdrant_behavioral_collections_delete_001), probing the
  endpoint's only typed request parameter: the OPTIONAL query param timeout
  (versioned v-1-18-x OpenAPI: {in: query, type: integer, minimum: 1};
  raw_knowledge parameter description: "query: min 1"). Query values travel
  as wire strings, so the attack targets the SERVER-SIDE coercion/validation
  gap, not client typing.
  G4 positive control: DELETE ?timeout=5 (documented-legal: integer >= 1)
  must be accepted - 200 + envelope result=true, and the collection must
  then be invisible (GET -> 404).
  Attacks (each on a fresh premise-verified collection):
    timeout=abc  - unparseable value; the integer schema cannot be
                   satisfied, so a 200 acceptance means the malformed value
                   was silently swallowed (BS-01 shape) = Type1_IllegalSuccess
    timeout=0    - parseable but BELOW the declared minimum 1; a 200
                   acceptance honors an out-of-contract value =
                   Type1_IllegalSuccess per the published min-1 schema
    timeout=-3   - negative integer, same minimum violation family
  Expected refusal class: 400/422 (clean). State-integrity follow-up on every
  REFUSED leg: the collection must still be gettable (GET -> 200) - a refusal
  that nevertheless destroyed the collection = Type4. 5xx with /healthz
  alive = Type3. 404 on a premise-verified name = premise broken ->
  SCRIPT_ERROR.
  [chunk_collections+delete coverage: type_coercion x
   qdrant_behavioral_collections_delete_001 (timeout query param: unparseable
   / below-minimum / negative, plus the documented-legal control)]
Oracle: DELETE ?timeout=5 -> 200 with result=true and the collection gone;
  DELETE ?timeout=abc / 0 / -3 -> clean 400/422 refusal with the collection
  still intact; any 2xx acceptance of the three malformed/below-minimum
  values = Type1_IllegalSuccess (integer minimum 1 declared by the versioned
  OpenAPI); 5xx with /healthz alive = Type3_RuntimeFailure; a refused leg
  whose collection vanished = Type4_StateLogicViolation.

Rationale (G4/G5/G7): each attack value is anchored to a distinct clause of
  the declared schema (type=integer for "abc"; minimum=1 for 0 and -3), so
  every leg has a spec-derived disposition; the positive control proves the
  refusal (if any) is about the value, not about the parameter itself.
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

print("[path derivation] drop_collection = /collections/{name} "
      "(raw_knowledge api_endpoints[collections+delete].url = /collections/{collection_name}; "
      "timeout is a QUERY param per the same entry - blocking params never go in the body)")

PFX = "scd06" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4
CREATED = []


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (forwards body/path_params/query_params/
    timeout exactly - standing lesson)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


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
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; "
                         f"a schema-violating query value must be refused with a clean "
                         f"4xx, never crash the server; body: {str(raw)[:200]}"))
        return False
    return True


def fresh_collection(tag, findings):
    """Create + premise-verify a fresh PFX-prefixed collection. Returns name
    or None (after recording a SCRIPT_ERROR finding)."""
    name = PFX + "_" + tag
    st, raw = safe_request("PUT", "create_collection",
                           body={"vectors": {"size": DIM, "distance": "Cosine"}},
                           path_params={"name": name}, timeout=60)
    print(f"[create {name}] status={st} raw={str(raw)[:180]}")
    if not transport_gate(f"create {tag}", st, raw, findings):
        return None
    if st != 200:
        findings.append((3, f"SCRIPT-ERROR: leg {tag} setup create got {st}: "
                            f"{str(raw)[:150]}"))
        return None
    CREATED.append(name)
    gst, graw = safe_request("GET", "describe_collection",
                             path_params={"name": name}, timeout=30)
    if gst != 200:
        findings.append((3, f"SCRIPT-ERROR: leg {tag} premise - GET after create "
                            f"returned {gst}: {str(graw)[:120]}"))
        return None
    return name


def state_after(tag, name, findings):
    """GET the collection after the leg's DELETE; returns 'gone' | 'intact' |
    None (unadjudicable)."""
    st, raw = safe_request("GET", "describe_collection",
                           path_params={"name": name}, timeout=30)
    print(f"[state after {tag}] GET {name} -> {st} raw={str(raw)[:160]}")
    if not transport_gate(f"state-after {tag}", st, raw, findings):
        return None
    if st == 404:
        return "gone"
    if st == 200:
        return "intact"
    print(f"[conflict-zone] state-after {tag}: GET returned {st}; excluded")
    return None


def check_envelope_true(tag, st, raw, findings):
    try:
        env = json.loads(raw) if raw else {}
        ok_env = isinstance(env.get("result"), bool) and env["result"]
    except Exception:
        ok_env = False
    if not ok_env:
        findings.append((2, f"Type4_StateLogicViolation: {tag} 200 but envelope "
                            f"violates result:boolean=true grid "
                            f"(collections+delete response_shape): {str(raw)[:200]}"))
        return False
    return True


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- G4 positive control: documented-legal timeout=5 ----
        n = fresh_collection("ctl", findings)
        if n is None:
            finish(findings)
            return
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": n},
                               query_params={"timeout": 5}, timeout=60)
        print(f"[control DELETE ?timeout=5] status={st} raw={str(raw)[:250]}")
        if not transport_gate("control timeout=5", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((2, f"Type1_IllegalRejection: control DELETE with the "
                                f"documented-legal query timeout=5 (integer >= 1) was "
                                f"refused with {st}; the parameter is declared optional "
                                f"integer min 1 - legal usage must be accepted; "
                                f"raw={str(raw)[:250]}"))
        else:
            check_envelope_true("control timeout=5", st, raw, findings)
            if state_after("control", n, findings) == "intact":
                findings.append((2, f"Type4_StateLogicViolation: control delete 200 "
                                    f"but '{n}' is still gettable (must be invisible "
                                    f"after a 200 delete)"))
            else:
                print("[conform] control: 200 result=true and collection gone")

        # ---- attacks: malformed / below-minimum timeout values ----
        attacks = [
            ("abc", "abc", "unparseable value 'abc' (declared type integer)"),
            ("zero", 0, "below-minimum value 0 (declared minimum 1)"),
            ("neg", -3, "negative value -3 (declared minimum 1)"),
        ]
        for item in attacks:
            tag, value, why = item[0], item[1], item[2]
            n = fresh_collection(tag, findings)
            if n is None:
                finish(findings)
                return
            st, raw = safe_request("DELETE", "drop_collection",
                                   path_params={"name": n},
                                   query_params={"timeout": value}, timeout=60)
            print(f"[attack DELETE ?timeout={value!r}] status={st} raw={str(raw)[:250]}")
            if not transport_gate(f"attack timeout={value!r}", st, raw, findings):
                finish(findings)
                return
            if 200 <= st <= 299:
                findings.append((2, f"Type1_IllegalSuccess: DELETE with "
                                    f"timeout={value!r} was ACCEPTED with {st}; the "
                                    f"versioned v-1-18-x OpenAPI declares the timeout "
                                    f"query as integer minimum 1 - {why} must be "
                                    f"refused, not silently honored (Blindspot BS-01); "
                                    f"raw={str(raw)[:250]}"))
                continue
            if st == 404:
                findings.append((3, f"SCRIPT-ERROR: attack timeout={value!r} got 404 "
                                    f"on a premise-verified collection {n}: "
                                    f"{str(raw)[:150]}"))
                continue
            if st in (400, 422):
                print(f"[conform] attack timeout={value!r}: cleanly refused with {st}")
            else:
                print(f"[conflict-zone] attack timeout={value!r}: non-declared status "
                      f"{st} (neither 2xx acceptance nor clean 400/422); measured, "
                      f"not adjudicated")
            # state integrity: a refused delete must not have destroyed the target
            s = state_after(f"attack {value!r}", n, findings)
            if s == "gone":
                findings.append((2, f"Type4_StateLogicViolation: DELETE with "
                                    f"timeout={value!r} was refused ({st}) yet the "
                                    f"collection '{n}' was destroyed - refusal and "
                                    f"effect disagree"))
            elif s == "intact":
                print(f"[conform] state integrity: '{n}' intact after the refusal")

        finish(findings)
    finally:
        # destructive-safety: only self-created, PFX-prefixed names are dropped
        for n in list(CREATED):
            try:
                rt.drop_collection(n)
            except Exception as e:
                print(f"cleanup warning (drop {n}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: timeout query schema enforced (abc/0/-3 refused cleanly with the "
          "collection intact; documented-legal timeout=5 accepted 200 result=true)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
