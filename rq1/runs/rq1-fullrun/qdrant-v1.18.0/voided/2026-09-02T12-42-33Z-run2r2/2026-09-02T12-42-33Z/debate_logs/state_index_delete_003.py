#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_003
# strategy: upsert_idempotence
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: upsert_idempotence (Strategy 3: repeated-mutation idempotence, with
  payload-index DELETE as the repeated mutation) x
  qdrant_state_index_delete_001 clause A ("delete of a non-existent payload
  index is an idempotent success"). Two legs hammer the SAME DELETE
  field_name K=6 times each: leg 1 deletes f_absent (never indexed, field
  absent from every payload) from the very start; leg 2 creates the f_kw
  index once, deletes it once, then repeats the identical DELETE 5 more
  times on the now-non-existent index. After each leg the state must have
  CONVERGED (describe payload_schema absence, exact count unchanged, scroll
  payload snapshot unchanged, filtered count on the field still resolving
  via full-scan filtering) - repeated application of an idempotent delete
  must neither error-escalate (404/409/5xx) nor disturb data at any repeat
  index. Rationale for the mutation point (G6): duplication is exactly the
  dimension where REST idempotence implementations leak internal state -
  e.g. a delete that succeeds once but returns 404 on the second call, or
  one that re-triggers index teardown and drops payload keys.
  [chunk_index+delete coverage: upsert_idempotence x
  qdrant_state_index_delete_001 (clause A: repeat-index escalation both
  never-created and previously-deleted legs + state convergence)]
Oracle: all 12 DELETE calls (6 never-created + 1 real + 5 re-deletes)
  return HTTP 200 with no escalation as the repeat index grows; describe
  result.payload_schema never contains f_absent/f_kw after their legs; exact
  count stays exactly 10 and the scroll payload snapshot stays deep-equal to
  baseline between and after both legs; filtered count on f_kw=k0 stays
  exactly 3 (ids 3,6,9; EXPECT_K0) throughout (filter survives without
  the index). Any repeat
  returning 4xx (e.g. 404 on the 2nd+ delete) = Type1_IllegalSuccess;
  5xx/transport while /healthz alive = Type3_RuntimeFailure; schema residue,
  count drift or payload mutation between repeats = Type4_StateLogicViolation
  (qdrant_state_index_delete_001)
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
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'count', 'scroll') if k in rt.PATHS]}")

K_REPEATS = 6
FLT_KW0 = {"must": [{"key": "f_kw", "match": {"value": "k0"}}]}


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
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


def scroll_payloads(tag, collection):
    s, raw = safe_request("POST", "scroll",
                          body={"limit": 100, "with_payload": True},
                          path_params={"name": collection})
    print(f"[{tag}] scroll status={s} raw={str(raw)[:200]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None, False
    snap = {}
    for p in res["points"]:
        if isinstance(p, dict) and "id" in p:
            snap[p["id"]] = p.get("payload")
    return snap, True


def describe_payload_schema(tag, collection):
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": collection})
    print(f"[{tag}] describe status={s} raw={str(raw)[:300]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict):
        return None, False
    ps = res.get("payload_schema")
    if ps is None:
        return {}, True
    if not isinstance(ps, dict):
        return None, False
    return ps, True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd3_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []
    N = 10

    pts = [
        {"id": i,
         "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {"f_kw": "k0" if i % 3 == 0 else "k1",
                     "f_int": i}}
        for i in range(1, N + 1)
    ]
    # k0 at ids 3,6,9 -> exactly 3; recompute to stay honest with the oracle
    EXPECT_K0 = sum(1 for p in pts if p["payload"]["f_kw"] == "k0")

    try:
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        cnt0, ok0 = get_count("baseline count", C)
        snap0, ok0s = scroll_payloads("baseline scroll", C)
        fk0, okf0 = get_count("baseline filtered f_kw=k0", C, flt=FLT_KW0)
        if not ok0 or cnt0 != N or not ok0s or not okf0 or fk0 != EXPECT_K0:
            print(f"VERDICT: SCRIPT_ERROR - baseline cnt={cnt0} filt={fk0}")
            return "SCRIPT_ERROR"

        def repeat_deletes(field, times, DEFECTS):
            """Same DELETE repeated `times`; returns list of statuses."""
            statuses = []
            for rep in range(1, times + 1):
                s, raw = safe_request("DELETE", "delete_index",
                                      path_params={"name": C,
                                                   "field_name": field},
                                      query_params={"wait": "true"})
                statuses.append(s)
                print(f"[repeat {rep}/{times} delete {field}] status={s} "
                      f"raw={str(raw)[:200]}")
                if s in (200, 201):
                    continue
                if s == 0 or 500 <= s <= 599:
                    if liveness(f"repeat {rep} delete {field}"):
                        DEFECTS.append(
                            f"(delete {field} rep {rep}) status {s} while "
                            f"/healthz alive - Type3_RuntimeFailure - "
                            f"raw={str(raw)[:160]}")
                else:
                    DEFECTS.append(
                        f"(delete {field} rep {rep}/{times}) idempotent delete "
                        f"escalated to HTTP {s} - Type1_IllegalSuccess - "
                        f"raw={str(raw)[:160]} "
                        f"(qdrant_state_index_delete_001 clause A)")
            return statuses

        # ---- leg 1: never-created field, K repeats from a clean state ----
        st_leg1 = repeat_deletes("f_absent", K_REPEATS, DEFECTS)

        psA, okpsA = describe_payload_schema("describe after leg1", C)
        if okpsA and ("f_absent" in psA or "f_kw" in psA):
            DEFECTS.append(
                f"(describe) schema contains never-created indexes: "
                f"{[f for f in ('f_absent', 'f_kw') if f in psA]} - "
                f"Type4_StateLogicViolation - echo={str(psA)[:200]}")

        # ---- leg 2: create once, delete once, then 5 identical re-deletes ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": "f_kw",
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[create f_kw index] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"
        psB, okpsB = describe_payload_schema("describe with f_kw index", C)
        if okpsB and "f_kw" not in psB:
            DEFECTS.append(
                "(describe) f_kw index created with 200 but absent from "
                "payload_schema - Type4_StateLogicViolation - ack without "
                f"persistence - echo={str(psB)[:200]}")

        st_leg2 = repeat_deletes("f_kw", K_REPEATS, DEFECTS)

        psC, okpsC = describe_payload_schema("describe after leg2", C)
        if okpsC and "f_kw" in psC:
            DEFECTS.append(
                f"(describe) f_kw index still present after {K_REPEATS} "
                f"deletes: echo={str(psC.get('f_kw'))[:160]} - "
                f"Type4_StateLogicViolation - non-convergent state")

        # ---- convergence of the data plane between/after the legs ----
        cnt1, ok1 = get_count("count after legs", C)
        snap1, ok1s = scroll_payloads("scroll after legs", C)
        fk1, okf1 = get_count("filtered f_kw=k0 after legs", C, flt=FLT_KW0)
        if ok1 and cnt1 != N:
            DEFECTS.append(
                f"(count) repeated idempotent deletes changed count: "
                f"{cnt1} != {N} - Type4_StateLogicViolation")
        if ok1s and snap1 != snap0:
            diff = {k for k in set(snap0) | set(snap1)
                    if snap0.get(k) != snap1.get(k)}
            DEFECTS.append(
                f"(payload) repeated idempotent deletes mutated {len(diff)} "
                f"point payload(s): ids={sorted(diff)[:8]} - "
                f"Type4_StateLogicViolation")
        if okf1 and fk1 != EXPECT_K0:
            DEFECTS.append(
                f"(filter) filtered count on f_kw after index teardown={fk1}, "
                f"expected {EXPECT_K0} - Type4_StateLogicViolation - data "
                f"must survive index deletion")

        # ---- summary ----
        print(f"[summary] leg1_statuses={st_leg1} leg2_statuses={st_leg2} "
              f"count={cnt1 if ok1 else None} filt={fk1 if okf1 else None} "
              f"payload_stable={snap0 == snap1 if ok1s else 'n/a'} "
              f"defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print(f"repeat-idempotence: {K_REPEATS}+{K_REPEATS} identical deletes "
              f"all 200 with no escalation; state converged (no schema "
              f"residue, count={N}, filter={EXPECT_K0}, payload snapshot "
              f"identical) - NO_DEFECT")
        return "NO_DEFECT"
    finally:
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
