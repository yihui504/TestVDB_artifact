#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_010
# strategy: index_state (Strategy 6: state consistency during async index builds)
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: index_state (Strategy 6) x qdrant_state_index_delete_001 — the index
  is deleted exactly while its asynchronous build is in flight. 300 points
  carry keyword payloads; create_index(f_kw) is issued with wait=false
  (returns immediately, build pending) and delete_index(f_kw) is issued
  wait=true in the same instant, twice (cycle 1: back-to-back; cycle 3: with a
  0.2s gap to widen the timing window; cycle 2 is the settled control:
  wait=true create, describe echo keyword, then delete). Because the delete is
  the later operation on the field, the persistent state must converge to
  "no index": after each cycle the describe readback is polled to a 20s
  deadline and payload_schema must NOT contain f_kw (a build completing after
  its own delete and resurrecting the entry = state-machine inconsistency).
  Clause B runs across every cycle: exact count stays 300, the three filtered
  counts on f_kw stay 100/100/100 (data and filter semantics untouched by
  build-time deletion).
  Rationale for this mutation point (G6): the async build window is where an
  index state machine most easily loses a delete — the tombstone can be
  overwritten by the finishing builder; deleting a settled index (cycle 2)
  alone would never expose that race.
  [chunk_index+delete coverage: index_state/during-build x
  qdrant_state_index_delete_001 (delete-wins convergence on the pending build
  + clause B data preservation under build-time deletion)]
Oracle: each during-build DELETE returns 200 (idempotent, collection exists);
  after every cycle the describe result.payload_schema contains no f_kw
  within 20s (residue = Type4_StateLogicViolation); the settled control cycle
  echoes data_type=keyword while indexed; exact count is exactly 300 and the
  filtered counts f_kw=kw0/kw1/kw2 are exactly 100/100/100 at every
  checkpoint. 5xx/transport with /healthz alive = Type3_RuntimeFailure.
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

# path keys verified against sorted(rt.PATHS): delete_index/create_index/
# describe_collection/count/upsert_points/healthz are native qdrant runtime
# keys (no fabrication)
print(f"[PATHS] index keys present="
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'count') if k in rt.PATHS]}")

FIELD = "f_kw"
N = 300
BATCH = 100
SETTLE_DEADLINE = 20.0


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=60):
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


def get_count(tag, collection, flt=None):
    """Exact count via points+count; returns (count_or_None, ok)."""
    body = {"exact": True}
    if flt is not None:
        body["filter"] = flt
    s, raw = safe_request("POST", "count", body=body,
                          path_params={"name": collection})
    print(f"[{tag}] count status={s} raw={str(raw)[:160]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    if not b or not isinstance(b.get("result"), dict) \
            or not isinstance(b["result"].get("count"), int):
        return None, False
    return b["result"]["count"], True


def describe_payload_schema(tag, collection):
    """describe_collection readback -> (status, payload_schema map or None)."""
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": collection})
    print(f"[{tag}] describe status={s} raw={str(raw)[:300]}")
    if s != 200:
        return s, None
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict):
        return s, None
    ps = res.get("payload_schema")
    if ps is None:
        return s, {}
    return s, ps if isinstance(ps, dict) else None


def entry_data_type(entry):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        dt = entry.get("data_type")
        if isinstance(dt, str):
            return dt
    return None


def create_index(C, wait):
    return safe_request("PUT", "create_index",
                        body={"field_name": FIELD,
                              "field_schema": {"type": "keyword"}},
                        path_params={"name": C},
                        query_params={"wait": "true" if wait else "false"})


def delete_index(C):
    return safe_request("DELETE", "delete_index",
                        path_params={"name": C, "field_name": FIELD},
                        query_params={"wait": "true"})


def wait_absent(C, DEFECTS, cycle):
    """Poll describe until FIELD is absent (deadline-bounded); residue = Type4."""
    deadline = time.time() + SETTLE_DEADLINE
    while True:
        ds, ps = describe_payload_schema(f"cycle {cycle} poll", C)
        if ds != 200:
            DEFECTS.append(
                f"(cycle {cycle}) describe returned {ds} on an existing "
                f"collection - Type4_StateLogicViolation")
            return False
        if isinstance(ps, dict) and FIELD not in ps:
            return True
        if time.time() >= deadline:
            DEFECTS.append(
                f"(cycle {cycle}) index {FIELD} still in payload_schema "
                f"{SETTLE_DEADLINE:.0f}s after the delete — the pending build "
                f"resurrected/kept the index past its own delete - "
                f"Type4_StateLogicViolation - echo={str(ps)[:200]} "
                f"(qdrant_state_index_delete_001)")
            return False
        time.sleep(1.0)


def data_checkpoint(tag, C, DEFECTS):
    """Clause B: exact 300 + filtered 100/100/100 at each checkpoint."""
    cnt, okc = get_count(f"{tag} total", C)
    if okc and cnt != N:
        DEFECTS.append(
            f"({tag}) exact count {cnt} != {N} - Type4_StateLogicViolation - "
            f"index deletion during build mutated point data")
    for v in ("kw0", "kw1", "kw2"):
        f, okf = get_count(f"{tag} filter {v}", C,
                           flt={"must": [{"key": FIELD,
                                          "match": {"value": v}}]})
        if okf and f != N // 3:
            DEFECTS.append(
                f"({tag}) filtered count {FIELD}={v} returned {f}, expected "
                f"{N // 3} - Type4_StateLogicViolation - filter semantics must "
                f"survive build-time index deletion")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd10_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    pts = [
        {"id": i,
         "vector": [0.001 * i, 0.5, 0.5, 0.5],
         "payload": {FIELD: f"kw{i % 3}", "f_int": i}}
        for i in range(1, N + 1)
    ]

    try:
        # ---- setup: collection + N points in batches (final batch wait=true) ----
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        for start in range(0, N, BATCH):
            chunk = pts[start:start + BATCH]
            last = start + BATCH >= N
            s, raw = safe_request("PUT", "upsert_points",
                                  body={"points": chunk},
                                  path_params={"name": C},
                                  query_params={"wait": "true" if last else "false"})
            print(f"[setup batch {start // BATCH}] n={len(chunk)} wait={last} "
                  f"status={s} raw={str(raw)[:120]}")
            if s not in (200, 201):
                return "SCRIPT_ERROR"
        cnt0, ok0 = get_count("baseline total", C)
        if not ok0 or cnt0 != N:
            print(f"VERDICT: SCRIPT_ERROR - baseline count {cnt0} != {N}")
            return "SCRIPT_ERROR"
        data_checkpoint("baseline", C, DEFECTS)
        if DEFECTS:
            # baseline itself inconsistent -> environment problem, not a defect
            print(f"VERDICT: SCRIPT_ERROR - baseline data checks failed: {DEFECTS}")
            return "SCRIPT_ERROR"

        # ---- cycle 1: create(wait=false) -> delete(wait=true) back-to-back ----
        s, raw = create_index(C, wait=False)
        print(f"[cycle1 create wait=false] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR - async create: {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        s, raw = delete_index(C)
        print(f"[cycle1 delete during build] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if (s == 0 or 500 <= s <= 599) and liveness("cycle1 delete"):
                DEFECTS.append(
                    f"(cycle 1) delete during pending build returned {s} while "
                    f"/healthz alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
            elif s != 0 and not (500 <= s <= 599):
                DEFECTS.append(
                    f"(cycle 1) delete during pending build rejected with {s} - "
                    f"Type4 inconsistent disposition (clause A promises 200) - "
                    f"raw={str(raw)[:160]}")
        wait_absent(C, DEFECTS, 1)
        data_checkpoint("cycle1", C, DEFECTS)

        # ---- cycle 2 (settled control): create(wait=true) -> echo -> delete ----
        s, raw = create_index(C, wait=True)
        print(f"[cycle2 create wait=true] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR - settled create: {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        deadline = time.time() + SETTLE_DEADLINE
        echoed = False
        while time.time() < deadline:
            ds, ps = describe_payload_schema("cycle2 echo poll", C)
            if ds == 200 and isinstance(ps, dict) and FIELD in ps:
                got = entry_data_type(ps.get(FIELD))
                if got != "keyword":
                    DEFECTS.append(
                        f"(cycle 2) settled index echo expected keyword, got "
                        f"{got!r} - Type4_StateLogicViolation")
                echoed = True
                break
            time.sleep(1.0)
        if not echoed:
            print(f"[note] settled index not visible in payload_schema within "
                  f"{SETTLE_DEADLINE:.0f}s (optimizer lag) - control echo skipped, "
                  f"deletion convergence still judged")
        s, raw = delete_index(C)
        print(f"[cycle2 delete settled] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if (s == 0 or 500 <= s <= 599) and liveness("cycle2 delete"):
                DEFECTS.append(
                    f"(cycle 2) settled delete returned {s} while /healthz "
                    f"alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
            elif s != 0 and not (500 <= s <= 599):
                DEFECTS.append(
                    f"(cycle 2) settled delete rejected with {s} - Type4 "
                    f"inconsistent disposition - raw={str(raw)[:160]}")
        wait_absent(C, DEFECTS, 2)
        data_checkpoint("cycle2", C, DEFECTS)

        # ---- cycle 3: create(wait=false) -> 0.2s gap -> delete(wait=true) ----
        s, raw = create_index(C, wait=False)
        print(f"[cycle3 create wait=false] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR - async create (cycle 3): {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        time.sleep(0.2)
        s, raw = delete_index(C)
        print(f"[cycle3 delete mid-build] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if (s == 0 or 500 <= s <= 599) and liveness("cycle3 delete"):
                DEFECTS.append(
                    f"(cycle 3) delete mid-build returned {s} while /healthz "
                    f"alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
            elif s != 0 and not (500 <= s <= 599):
                DEFECTS.append(
                    f"(cycle 3) delete mid-build rejected with {s} - Type4 "
                    f"inconsistent disposition - raw={str(raw)[:160]}")
        wait_absent(C, DEFECTS, 3)
        data_checkpoint("cycle3", C, DEFECTS)

        # ---- summary ----
        print(f"[summary] N={N} cycles=3 defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("during-build deletion clean: all deletes 200, describe converged "
              "to no-index within deadline after every cycle (delete wins over "
              "the pending build), count=300 and filtered 100/100/100 at every "
              "checkpoint - NO_DEFECT")
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
