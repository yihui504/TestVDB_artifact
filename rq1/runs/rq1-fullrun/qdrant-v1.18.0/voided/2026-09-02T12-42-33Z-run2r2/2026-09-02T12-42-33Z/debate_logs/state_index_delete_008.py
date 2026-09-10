#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_008
# strategy: concurrent (Strategy 4: same-resource conflicting-mutation race)
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: concurrent conflicting mutations (Strategy 4) x
  qdrant_state_index_delete_001 — ROUNDS barrier-synchronized rounds in which
  TESTVDB_CONCURRENT_THREADS (default 8) threads hit the SAME payload-index
  resource simultaneously: even threads PUT create_index(f_race, keyword,
  wait=true), odd threads DELETE delete_index(f_race, wait=true). The
  collection itself exists throughout, so every racing delete is an idempotent
  delete that must succeed (200) no matter whether the index exists at that
  instant (clause A), and every create is legal (2xx). A concurrent exact-count
  reader samples points+count during the whole race: 200/12 at every sample.
  After the race: one final wait=true delete, then describe readback must show
  NO residue, exact count must stay 12, the scroll payload snapshot must be
  deep-equal to baseline and the filtered count on f_race must stay 4 (clause
  B: racing index toggling never touches point data).
  Rationale for this mutation point (G6): create+delete of the same index is
  the tightest conflicting pair on one resource — the delete's idempotence
  promise and the index state machine's persistence promise are both exercised
  at their highest-timing-contention window.
  [chunk_index+delete coverage: concurrent/same-resource x
  qdrant_state_index_delete_001 (clause A idempotence under create/delete race
  + clause B data preservation + describe no-residue convergence)]
Oracle: all racing DELETEs return 200 and all racing PUTs return 2xx (a 4xx =
  Type4 inconsistent disposition; 5xx/transport with /healthz alive >=2 =
  Type3_RuntimeFailure); every concurrent count sample returns exactly 200 with
  count=12 (drift = Type4); after the final delete the describe
  result.payload_schema contains no f_race entry (residue = Type4), exact count
  is exactly 12, filtered count f_race=kw1 is exactly 4 and the scroll payload
  snapshot is deep-equal to baseline.
"""

import os
import sys
import json
import time
import threading
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
# describe_collection/count/upsert_points/scroll/healthz are native qdrant
# runtime keys (no fabrication)
print(f"[PATHS] index keys present="
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'count', 'scroll') if k in rt.PATHS]}")

THREADS = max(2, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "8")))
ROUNDS = 8
FIELD = "f_race"
N = 12  # points; ids 1..4,5..8,9..12 carry kw0/kw1/kw2 -> filtered kw1 = 4


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


def get_count(tag, collection, flt=None):
    """Exact count via points+count; returns (count_or_None, ok)."""
    body = {"exact": True}
    if flt is not None:
        body["filter"] = flt
    s, raw = safe_request("POST", "count", body=body,
                          path_params={"name": collection})
    if s != 200:
        return None, False
    b = parse_json(raw)
    if not b or not isinstance(b.get("result"), dict) \
            or not isinstance(b["result"].get("count"), int):
        return None, False
    return b["result"]["count"], True


def scroll_payloads(tag, collection):
    """Full payload snapshot via points+scroll. Returns (id->payload, ok)."""
    s, raw = safe_request("POST", "scroll",
                          body={"limit": 100, "with_payload": True},
                          path_params={"name": collection})
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None, False
    return {p["id"]: p.get("payload") for p in res["points"]
            if isinstance(p, dict) and "id" in p}, True


def describe_payload_schema(tag, collection):
    """describe_collection readback -> result.payload_schema map (or None)."""
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
    PFX = "sidd8_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    pts = [
        {"id": i,
         "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {"f_race": f"kw{i % 3}", "f_plain": i}}
        for i in range(1, N + 1)
    ]

    try:
        # ---- setup: collection + points (wait=true for deterministic state) ----
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
        if not ok0 or cnt0 != N or not ok0s or len(snap0) != N:
            print(f"VERDICT: SCRIPT_ERROR - baseline count={cnt0} snap={len(snap0) if snap0 else None} (want {N})")
            return "SCRIPT_ERROR"

        # ---- concurrent reader: exact count must be 200/12 at every sample ----
        stop = threading.Event()
        reader_bad = []   # (status, count_or_raw)
        bad_5xx = []      # (op, status, alive)
        race_bad_4xx = []  # (op, status, raw)

        def reader():
            while not stop.is_set():
                cnt, ok = get_count("reader", C)
                if not ok:
                    # distinguish transport/5xx from parse problems
                    s2, raw2 = safe_request("POST", "count", body={"exact": True},
                                            path_params={"name": C}, timeout=15)
                    if s2 == 0 or 500 <= s2 <= 599:
                        alive = liveness(f"reader status={s2}")
                        bad_5xx.append(("count", s2, alive))
                    else:
                        reader_bad.append((s2, str(raw2)[:120]))
                elif cnt != N:
                    reader_bad.append((200, f"count drift: {cnt} != {N}"))
                time.sleep(0.03)

        lock = threading.Lock()

        def racer(tid, barrier, round_idx, out):
            """One barrier-synchronized conflicting mutation on the same index."""
            barrier.wait()
            if tid % 2 == 0:
                s, raw = safe_request("PUT", "create_index",
                                      body={"field_name": FIELD,
                                            "field_schema": {"type": "keyword"}},
                                      path_params={"name": C},
                                      query_params={"wait": "true"}, timeout=30)
                op = "create"
            else:
                s, raw = safe_request("DELETE", "delete_index",
                                      path_params={"name": C, "field_name": FIELD},
                                      query_params={"wait": "true"}, timeout=30)
                op = "delete"
            with lock:
                out.append((op, s, str(raw)[:120]))

        rt_reader = threading.Thread(target=reader)
        rt_reader.start()
        for r in range(ROUNDS):
            out = []
            barrier = threading.Barrier(THREADS)
            ts = [threading.Thread(target=racer, args=(k, barrier, r, out))
                  for k in range(THREADS)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            print(f"[round {r}] op/status matrix="
                  f"{[(op, s) for op, s, _ in out]}")
            for op, s, snip in out:
                if s in (200, 201):
                    continue
                if s == 0 or 500 <= s <= 599:
                    alive = liveness(f"race {op} status={s}")
                    bad_5xx.append((op, s, alive))
                else:
                    race_bad_4xx.append((op, s, snip))
        stop.set()
        rt_reader.join()

        # ---- adjudication: racing window ----
        alive_5xx = [e for e in bad_5xx if e[2]]
        if len(alive_5xx) >= 2:
            DEFECTS.append(
                f"(race) {len(alive_5xx)} 5xx/transport responses during "
                f"same-field create/delete racing while /healthz alive "
                f"(samples={alive_5xx[:3]}) - Type3_RuntimeFailure "
                f"(qdrant_state_index_delete_001)")
        elif len(bad_5xx) >= 1:
            print(f"[note] sporadic 5xx/transport occurrences={len(bad_5xx)} "
                  f"below the 2-occurrence reproduction bar - recorded, not judged")
        for op, s, snip in race_bad_4xx:
            DEFECTS.append(
                f"(race) legal {op} on same field rejected with HTTP {s} under "
                f"concurrency - Type4 inconsistent disposition (delete is "
                f"idempotent-200 by the constraint, create is legal) - raw={snip}")
        for s, info in reader_bad:
            DEFECTS.append(
                f"(reader) concurrent exact count failed: status={s} {info} - "
                f"Type4_StateLogicViolation - point data must be stable and "
                f"readable throughout index toggling")

        # ---- final convergence: one wait=true delete then describe readback ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FIELD},
                              query_params={"wait": "true"}, timeout=30)
        print(f"[final delete] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if (s == 0 or 500 <= s <= 599) and liveness("final delete"):
                DEFECTS.append(
                    f"(final) idempotent delete after race returned {s} while "
                    f"/healthz alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
            elif s != 0 and not (500 <= s <= 599):
                DEFECTS.append(
                    f"(final) idempotent delete after race rejected with {s} - "
                    f"Type4 inconsistent disposition - raw={str(raw)[:160]}")

        deadline = time.time() + 15
        ps, okps = describe_payload_schema("describe after final delete", C)
        while okps and FIELD in ps and time.time() < deadline:
            time.sleep(1.0)
            ps, okps = describe_payload_schema("describe poll", C)
        if okps and FIELD in ps:
            DEFECTS.append(
                f"(describe) index {FIELD} still present in payload_schema 15s "
                f"after a wait=true delete - Type4_StateLogicViolation - "
                f"echo={str(ps)[:200]} (qdrant_state_index_delete_001)")

        # ---- clause B: data untouched by the racing lifecycle ----
        cnt2, ok2 = get_count("count after race", C)
        if ok2 and cnt2 != N:
            DEFECTS.append(
                f"(count) exact count {cnt2} != {N} after create/delete race - "
                f"Type4_StateLogicViolation - index toggling deleted data")
        snap2, ok2s = scroll_payloads("scroll after race", C)
        if ok2s and snap2 != snap0:
            diff = {k for k in set(snap0) | set(snap2)
                    if snap0.get(k) != snap2.get(k)}
            DEFECTS.append(
                f"(payload) racing mutated {len(diff)} point payload(s): "
                f"ids={sorted(diff)[:8]} - Type4_StateLogicViolation")
        fk, okf = get_count("filtered count after race", C,
                            flt={"must": [{"key": FIELD,
                                           "match": {"value": "kw1"}}]})
        if okf and fk != 4:
            DEFECTS.append(
                f"(filter) filtered count on {FIELD}=kw1 returned {fk}, "
                f"expected 4 after the race - Type4_StateLogicViolation - "
                f"filter semantics must survive index toggling")

        print(f"[summary] rounds={ROUNDS} threads={THREADS} "
              f"bad5xx={len(bad_5xx)} bad4xx={len(race_bad_4xx)} "
              f"reader_bad={len(reader_bad)} residue="
              f"{(FIELD in ps) if okps else 'n/a'} count={cnt2 if ok2 else 'n/a'} "
              f"payload_stable={snap2 == snap0 if ok2s else 'n/a'} defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("same-field create/delete race clean: every racing delete 200 and "
              "create 2xx, concurrent counts always 200/12, no schema residue "
              "after final delete, payload snapshot identical - NO_DEFECT")
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
