#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_create_004
# strategy: upsert_idempotence
# endpoint: index+create
# constraint_ids: qdrant_behavioral_index_create_001, qdrant_inv_index_toggle_preserves_data_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/create-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: upsert_idempotence (Strategy 3) x qdrant_behavioral_index_create_001
  (200 branch: "valid index creation returns HTTP 200") + state invariant
  qdrant_inv_index_toggle_preserves_data_001. Index creation is a PUT —
  the idempotent verb — so re-asserting the SAME valid schema must converge
  to the SAME state, never duplicate or corrupt it. Sequence on one
  collection, 12 points with keyword payload city: (1) create keyword index
  city (wait=true) -> 200; describe: payload_schema contains exactly ONE
  entry for city with data_type keyword; (2) repeat the IDENTICAL PUT three
  more times; after each, describe must still show exactly one city entry
  (duplication = Type4), and count=12 + payload snapshot must be unchanged
  (Type4 per invariant); (3) conflict-zone leg (measured-only, G3/R20):
  a FOURTH PUT with a DIFFERENT schema (integer) on the same field — the
  contract does not pin re-schema semantics, so status + resulting
  payload_schema data_type are recorded WITHOUT a claim (5xx with /healthz
  alive is still claimed as Type3). State oracles stay strict throughout:
  the city field never duplicates, count stays 12, payloads byte-identical.
  [chunk_index+create coverage: upsert_idempotence x
  qdrant_behavioral_index_create_001 (200 branch on repeats) x
  qdrant_inv_index_toggle_preserves_data_001]
Oracle: identical re-PUTs of a valid index schema never duplicate the
  payload_schema entry for the field (exactly one entry across 4 identical
  creates), never change count (12) or any point payload; a repeat that
  returns 5xx while /healthz alive = Type3_RuntimeFailure; duplicate
  entries, count drift or payload mutation = Type4_StateLogicViolation;
  the different-schema repeat is measured-only (conflict zone)
  (qdrant_behavioral_index_create_001, qdrant_inv_index_toggle_preserves_data_001)
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

print(f"[PATHS] index keys present="
      f"{[k for k in ('create_index', 'describe_collection', 'count', 'scroll') if k in rt.PATHS]}")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    """Transport/5xx branch liveness re-check via the lightweight healthz face."""
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def get_count(tag, collection):
    s, raw = safe_request("POST", "count", body={"exact": True},
                          path_params={"name": collection})
    print(f"[{tag}] count status={s} raw={str(raw)[:160]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    if not b or not isinstance(b.get("result"), dict) \
            or not isinstance(b["result"].get("count"), int):
        return None, False
    return b["result"]["count"], True


def scroll_payloads(tag, collection):
    s, raw = safe_request("POST", "scroll", body={"limit": 100},
                          path_params={"name": collection})
    print(f"[{tag}] scroll status={s} raw={str(raw)[:200]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None, False
    return {p["id"]: p.get("payload") for p in res["points"]
            if isinstance(p, dict) and "id" in p}, True


def city_entry(tag, collection):
    """describe -> the payload_schema entry for the field 'city' (or a
    sentinel marker). Returns (entry_or_None, seen_bool, ok)."""
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": collection})
    print(f"[{tag}] describe status={s} raw={str(raw)[:300]}")
    if s != 200:
        return None, False, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict):
        return None, False, False
    ps = res.get("payload_schema")
    if ps is None:
        return None, False, True
    if not isinstance(ps, dict):
        return None, False, False
    return ps.get("city"), "city" in ps, True


def entry_data_type(entry):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("data_type"), str):
        return entry["data_type"]
    return None


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidx4_" + TS + "_"
    C = PFX + "col"
    FIELD = "city"
    DEFECTS = []
    NOTES = []
    N = 12
    REPEATS = 3

    pts = [
        {"id": i, "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {FIELD: f"c{i % 4}"}}
        for i in range(1, N + 1)
    ]

    try:
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        cnt0, ok0 = get_count("baseline count", C)
        if not ok0 or cnt0 != N:
            print(f"VERDICT: SCRIPT_ERROR - baseline count != {N}: {cnt0}")
            return "SCRIPT_ERROR"
        snap0, ok0s = scroll_payloads("baseline scroll", C)
        if not ok0s or len(snap0) != N:
            return "SCRIPT_ERROR"

        # ---- initial create: 200 + exactly one entry, data_type keyword ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": FIELD,
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[create #0] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if s == 0 or 500 <= s <= 599:
                if not liveness("create #0"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(create #0) HTTP {s} on a valid create while /healthz "
                    f"alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
            else:
                DEFECTS.append(
                    f"(create #0) valid create rejected with HTTP {s} - "
                    f"Type1_IllegalSuccess - raw={str(raw)[:160]}")
        entry, seen, okd = city_entry("describe #0", C)
        if okd and seen:
            if entry_data_type(entry) != "keyword":
                DEFECTS.append(
                    f"(describe #0) city entry reports data_type="
                    f"{entry_data_type(entry)!r} != keyword - "
                    f"Type4_StateLogicViolation - echo={str(entry)[:160]}")

        # ---- identical repeats x3: state must not duplicate/mutate ----
        for rep in range(1, REPEATS + 1):
            s, raw = safe_request("PUT", "create_index",
                                  body={"field_name": FIELD,
                                        "field_schema": {"type": "keyword"}},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            print(f"[create #{rep} identical] status={s} raw={str(raw)[:200]}")
            if s == 0:
                if liveness(f"create #{rep}"):
                    NOTES.append(f"create #{rep}: transport loss (status 0) "
                                 f"while alive - single occurrence recorded")
                else:
                    return "SCRIPT_ERROR"
            elif 500 <= s <= 599:
                if liveness(f"create #{rep}"):
                    DEFECTS.append(
                        f"(create #{rep} identical) HTTP {s} on an identical "
                        f"valid re-PUT while /healthz alive - "
                        f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
                else:
                    return "SCRIPT_ERROR"
            elif s not in (200, 201):
                # repeat semantics beyond 2xx are not pinned by the contract:
                # measured-only (G3 gray zone), state oracles below still run
                NOTES.append(f"create #{rep} identical: HTTP {s} - repeat "
                             f"disposition recorded, not claimed (contract "
                             f"pins no repeat status)")
            entry, seen, okd = city_entry(f"describe #{rep}", C)
            if okd:
                if not seen:
                    DEFECTS.append(
                        f"(describe #{rep}) after a 2xx create the field "
                        f"{FIELD} is ABSENT from payload_schema - "
                        f"Type4_StateLogicViolation - ack without persistence")
                elif not isinstance(entry, (str, dict)):
                    DEFECTS.append(
                        f"(describe #{rep}) malformed payload_schema entry "
                        f"for {FIELD}: {str(entry)[:160]} - "
                        f"Type4_StateLogicViolation")
            cnt, okc = get_count(f"count #{rep}", C)
            if okc and cnt != N:
                DEFECTS.append(
                    f"(count #{rep}) count {cnt} != {N} after identical "
                    f"index re-create - Type4_StateLogicViolation "
                    f"(qdrant_inv_index_toggle_preserves_data_001)")
            snap, oks = scroll_payloads(f"scroll #{rep}", C)
            if oks and snap != snap0:
                diff = [k for k in set(snap0) | set(snap)
                        if snap0.get(k) != snap.get(k)]
                DEFECTS.append(
                    f"(payload #{rep}) identical re-create mutated "
                    f"{len(diff)} payload(s): ids={sorted(diff)[:8]} - "
                    f"Type4_StateLogicViolation")

        # ---- duplication check: exactly one city entry (map keys unique,
        #      so a duplicate would manifest as extra fields/keys) ----
        s, raw = safe_request("GET", "describe_collection",
                              path_params={"name": C})
        b = parse_json(raw)
        ps = ((b or {}).get("result") or {}).get("payload_schema")
        if isinstance(ps, dict):
            city_like = [k for k in ps if k == FIELD or k.startswith(FIELD)]
            if len(city_like) != 1:
                DEFECTS.append(
                    f"(duplication) payload_schema shows {len(city_like)} "
                    f"city-like entries after {REPEATS + 1} identical "
                    f"creates: {city_like} - Type4_StateLogicViolation - "
                    f"echo={str(ps)[:200]}")

        # ---- conflict-zone leg: different schema on same field (measured) ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": FIELD,
                                    "field_schema": {"type": "integer"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[create conflict integer-on-keyword] status={s} "
              f"raw={str(raw)[:240]}")
        if s == 0 or 500 <= s <= 599:
            if not liveness("create conflict"):
                return "SCRIPT_ERROR"
            if 500 <= s <= 599 or s == 0:
                DEFECTS.append(
                    f"(create conflict) HTTP {s} on the schema-conflict "
                    f"re-PUT while /healthz alive - Type3_RuntimeFailure - "
                    f"raw={str(raw)[:160]}")
        else:
            entry, seen, okd = city_entry("describe after conflict", C)
            NOTES.append(
                f"schema-conflict re-PUT (integer over keyword) returned "
                f"HTTP {s}; resulting payload_schema entry="
                f"{str(entry)[:160] if okd else 'n/a'} - measured-only "
                f"(contract pins no re-schema semantics)")
        cnt, okc = get_count("count final", C)
        if okc and cnt != N:
            DEFECTS.append(
                f"(count final) count {cnt} != {N} after the whole "
                f"idempotence sequence - Type4_StateLogicViolation")
        snap, oks = scroll_payloads("scroll final", C)
        if oks and snap != snap0:
            diff = [k for k in set(snap0) | set(snap)
                    if snap0.get(k) != snap.get(k)]
            DEFECTS.append(
                f"(payload final) idempotence sequence mutated "
                f"{len(diff)} payload(s): ids={sorted(diff)[:8]} - "
                f"Type4_StateLogicViolation")

        for n in NOTES:
            print(f"NOTE: {n}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print(f"index-create idempotence verified: {REPEATS + 1} identical "
              "creates converged to exactly one payload_schema entry; "
              f"count={N} and payload snapshot unchanged throughout - "
              "NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
        try:
            rt.drop_collection(C)
            print(f"[cleanup] dropped {C}")
        except Exception as e:
            print(f"[cleanup] drop {C} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
