#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_create_019
# strategy: type_coercion
# endpoint: collections+create
# constraint_ids: qdrant_behavioral_collections_create_003
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - serde validation gaps let
#   null/array/string mismatches through silently, e.g. the R10
#   sparse_vectors:[] -> struct-from-seq acceptance on this same endpoint)
"""
Attack: type_coercion + behavioral_contract x
  qdrant_behavioral_collections_create_003 (chunk_collections+create-2of2;
  PUT /collections/{name} via runtime path_key create_collection). The
  assertion (evidence_tier=explicit, defect_type_if_violated=
  Type1_IllegalSuccess): invalid enum / malformed vectors config is
  rejected with HTTP 400, not 200. Shape-generalization family over the
  malformed-vectors parameter space, each leg on a FRESH name:
    (a) regression instance: distance 'Bogus' - the documented observed 400
        ('data did not match any variant of untagged enum VectorsConfig');
    (b) novel_candidate: distance 5 (integer where an enum string is
        required - numeric enum coercion);
    (c) novel_candidate: distance null (enum field nulled);
    (d) novel_candidate: size '4' (string where uint64 required - the
        classic string-to-int coercion);
    (e) novel_candidate: vectors [] (empty ARRAY where object|required map
        expected - same-family as the R10 sparse_vectors:[] silent
        struct-from-seq acceptance);
    (f) novel_candidate: vectors 'dense-vector' (string where object
        required).
  Every leg must return 400/422; state closure: a refused leg must leave
  NO collection behind (describe 404) - a 4xx that still created state is
  a Type4. SKIPPED: vectors={} (empty object) - covered by round 1of2
  (semantic_collections_create verdict NOT defect, shell-then-fill
  by-design evidence on record).
  [chunk_collections+create-2of2 coverage: type_coercion x
   qdrant_behavioral_collections_create_003 (6-leg malformed-vectors
   family, regression + 5 novel candidates)]
Oracle: each of the six malformed-vectors legs returns 400/422 - any
  200/201 = DEFECT_FOUND (Type1_IllegalSuccess, silent coercion); 5xx with
  /healthz alive = Type3_RuntimeFailure; and every refused leg's describe
  returns 404 - a 200 describe after a refused create = Type4_
  StateLogicViolation (rejected-but-created ghost state) - constraint
  qdrant_behavioral_collections_create_003.

Rationale (G1/G3/G6): the mutation points are chosen where serde leniency
  historically leaks (R10 measured sparse [] acceptance on this exact
  endpoint): sequence-to-struct, string-to-int, int-to-enum, null-enum.
  Each is a distinct coercion channel; hitting the family, not one shape,
  is what generalizes the 1of2 single-instance coverage.
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
print("# exploration_target: leg (a)=regression | legs (b)-(f)=novel_candidate")

PREFIX = "scc019_"
RUN = str(int(time.time()))
CREATED = []

# family enumeration: (tag, full create body, exploration role)
LEGS = [
    ("a_distance_bogus", {"vectors": {"size": 4, "distance": "Bogus"}}, "regression"),
    ("b_distance_int", {"vectors": {"size": 4, "distance": 5}}, "novel_candidate"),
    ("c_distance_null", {"vectors": {"size": 4, "distance": None}}, "novel_candidate"),
    ("d_size_string", {"vectors": {"size": "4", "distance": "Cosine"}}, "novel_candidate"),
    ("e_vectors_array", {"vectors": []}, "novel_candidate"),
    ("f_vectors_string", {"vectors": "dense-vector"}, "novel_candidate"),
]


def safe_request(method, path_key, body=None, path_params=None, query_params=None, timeout=60):
    """All HTTP through the runtime; forwards method/path_key/body/path_params/
    query_params/timeout exactly (standing lesson). Returns (status, raw_text)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


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
        # positive control: the SAME shape with legal values must be accepted
        # (G4 pairing - the family is only 'invalid' because of the mutated member)
        ctl = mkn("ctl_legal")
        st, raw = safe_request("PUT", "create_collection",
                               {"vectors": {"size": 4, "distance": "Cosine"}},
                               path_params={"name": ctl})
        print(f"[control-legal] status={st} raw={str(raw)[:250]}")
        if st not in (200, 201):
            if st == 0 and liveness("transport") != 200:
                script_error("transport failure on legal control create and /healthz down")
            script_error(f"legal control create failed with {st}; family baseline unavailable; raw={str(raw)[:200]}")
        CREATED.append(ctl)
        print("[control-legal] accepted - the mutated legs below differ only in the attacked member")

        for tag, body, role in LEGS:
            name = mkn(tag)
            st, raw = safe_request("PUT", "create_collection", body,
                                   path_params={"name": name})
            print(f"[{tag} ({role})] body={json.dumps(body)} status={st} raw={str(raw)[:300]}")
            if st == 0:
                if liveness(f"transport-{tag}") != 200:
                    script_error(f"{tag}: transport failure and /healthz down; no defect conclusion")
                script_error(f"{tag}: transport failure; /healthz alive; no defect conclusion")
            if 500 <= st <= 599:
                if liveness(f"5xx-{tag}") != 200:
                    script_error(f"{tag}: 5xx ({st}) and /healthz not 200; deployment unstable")
                defect("Type3_RuntimeFailure",
                       f"{tag}: malformed vectors config {body} raised server error "
                       f"{st} while /healthz is alive; raw={str(raw)[:200]}")
            if st in (200, 201):
                CREATED.append(name)
                defect("Type1_IllegalSuccess",
                       f"{tag} ({role}): malformed vectors config {json.dumps(body)} was "
                       f"ACCEPTED with {st} - assertion qdrant_behavioral_collections_"
                       f"create_003 declares HTTP 400 for invalid/malformed vectors "
                       f"config; raw={str(raw)[:250]}")
            if not (400 <= st <= 499):
                script_error(f"{tag}: unexpected status {st}; raw={str(raw)[:200]}")
            print(f"[{tag}] correctly rejected with {st}")

            # state closure: a refused create must leave nothing behind
            dst, draw = safe_request("GET", "describe_collection",
                                     path_params={"name": name})
            print(f"[{tag} describe] status={dst} raw={str(draw)[:200]}")
            if dst == 200:
                CREATED.append(name)
                defect("Type4_StateLogicViolation",
                       f"{tag}: create was refused {st} yet describe returns 200 - "
                       f"rejected-but-created ghost state; raw={str(draw)[:200]}")
            if dst == 404:
                print(f"[{tag}] no ghost collection - refusal left no state")
            elif dst == 0:
                if liveness(f"transport-describe-{tag}") != 200:
                    script_error(f"{tag}: describe transport failure and /healthz down")
                print(f"[{tag}] describe transport failure; /healthz alive; recorded")
            else:
                print(f"[{tag}] describe returned {dst} (recorded; 404 expected for a refused create)")

        print("[summary] all six malformed-vectors legs rejected in the 4xx family "
              "with no ghost state - constraint "
              "qdrant_behavioral_collections_create_003 holds")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
