#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_create_014
# strategy: concurrent
# endpoint: collections+create
# constraint_ids: qdrant_type_collections_create_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/create-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 7 (lifecycle concurrency) on PUT/GET/DELETE
  /collections/{name} (collections+create is the chunk's data-bearing
  endpoint; describe/count are the access face). While the collection is
  being dropped and re-created in a loop (drop -> create same name, valid
  vectors config {size:4, Cosine} per qdrant_type_collections_create_001),
  concurrent access threads hammer describe + points/count. The server must
  handle "collection temporarily absent" with 404 (or 503), never a 500.
  Blindspot: BS-03 Concurrency State Blindness.
  Phases: the race runs once; if exactly one 500 is observed, one extra
  confirmation phase runs (sporadic 500s reported only when seen >= 2 times
  total, avoiding race false positives). After the race the lifecycle thread
  ends on a create, so the final state must be: describe -> 200 with the
  requested vectors config intact (Type4 if the settled state is wrong).
  [chunk_collections+create-1of2 coverage: concurrent (lifecycle x access
  race) x qdrant_type_collections_create_001 (lifecycle body config)]
Oracle: during the race access threads see only {200, 404, 409, 503} — a 500
  is a defect signal (Type3_RuntimeFailure, claimed only after /healthz
  confirms liveness, and only when observed >= 2 times across phases);
  after the race describe -> 200 with readback vectors.size==4 /
  distance=="Cosine" (settled-state mismatch = Type4_StateLogicViolation)
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

CFG = {"vectors": {"size": 4, "distance": "Cosine"}}
LIFECYCLE_CYCLES = 6
ACCESS_ITERS = 6
THREADS = max(2, min(20, int(os.environ.get("TESTVDB_CONCURRENT_THREADS", "10"))))


def safe_request(method, path_key, path_params=None, body=None, query_params=None):
    """All HTTP through the runtime; inline liveness probes (GET healthz)
    stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params)


def run_race(name, counters):
    """One lifecycle x access race phase. Mutates counters dict:
    {'500': [...], 'transport': int, 'ok': int, 'absent': int}."""
    stop = threading.Event()

    def lifecycle():
        # start from a clean create so phase semantics are deterministic
        safe_request("PUT", "create_collection", path_params={"name": name}, body=CFG)
        for _ in range(LIFECYCLE_CYCLES):
            if stop.is_set():
                break
            try:
                safe_request("DELETE", "drop_collection", path_params={"name": name})
            except Exception:
                pass
            time.sleep(0.05)
            safe_request("PUT", "create_collection", path_params={"name": name},
                         body=CFG)
            time.sleep(0.05)
        # settle on an existing collection (final op = create)
        safe_request("PUT", "create_collection", path_params={"name": name}, body=CFG)

    def access(tid):
        for i in range(ACCESS_ITERS):
            if stop.is_set():
                break
            if (i + tid) % 2 == 0:
                s, raw = safe_request("GET", "describe_collection",
                                      path_params={"name": name})
            else:
                s, raw = safe_request("POST", "count", path_params={"name": name},
                                      body={"exact": True})
            if s == 500 or (501 <= s <= 599):
                counters["500"].append((s, raw[:160]))
            elif s == 0:
                counters["transport"] += 1
            elif s == 404 or s == 503:
                counters["absent"] += 1  # correct "temporarily absent" semantics
            elif 200 <= s < 300:
                counters["ok"] += 1
            else:
                counters.setdefault("other", []).append(s)
            time.sleep(0.03)

    lt = threading.Thread(target=lifecycle)
    lt.start()
    ats = [threading.Thread(target=access, args=(t,)) for t in range(THREADS)]
    for t in ats:
        t.start()
    for t in ats:
        t.join()
    lt.join()
    stop.set()


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sccr14_" + TS + "_"
    C = PFX + "race"
    DEFECTS = []

    try:
        counters = {"500": [], "transport": 0, "ok": 0, "absent": 0}
        run_race(C, counters)
        print(f"[phase1] 500s={len(counters['500'])} transport={counters['transport']} "
              f"ok={counters['ok']} absent(404/503)={counters['absent']} "
              f"other={counters.get('other', [])}")
        for s, r in counters["500"]:
            print(f"[phase1 5xx] status={s} raw={r}")

        # sporadic-500 confirmation: one extra phase when exactly one was seen
        if len(counters["500"]) == 1:
            print("[confirm] exactly one 5xx observed — running one confirmation phase")
            counters2 = {"500": [], "transport": 0, "ok": 0, "absent": 0}
            run_race(C, counters2)
            print(f"[phase2] 500s={len(counters2['500'])} ok={counters2['ok']} "
                  f"absent={counters2['absent']}")
            for s, r in counters2["500"]:
                print(f"[phase2 5xx] status={s} raw={r}")
            counters["500"].extend(counters2["500"])

        if counters["500"]:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[race liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
        if len(counters["500"]) >= 2:
            DEFECTS.append(
                f"(race) access endpoint returned 5xx {len(counters['500'])} "
                f"times while the collection was being dropped/recreated "
                f"(service alive per /healthz) — should be 404/503 'temporarily "
                f"absent', not internal error — Type3_RuntimeFailure — "
                f"samples={[r for _, r in counters['500'][:3]]}"
            )
        elif len(counters["500"]) == 1:
            print("OBSERVATION (race): single 5xx could not be reproduced in a "
                  "confirmation phase — recorded, not judged")

        if counters["transport"] > 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[post-race liveness] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"

        # settled-state check: lifecycle ended on create -> describe 200 + config
        time.sleep(0.3)
        gs, graw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[settled] describe status={gs} raw={graw[:240]}")
        if gs == 500 or gs == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[settled transport] healthz status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
        if gs != 200:
            DEFECTS.append(
                f"(settled) after the lifecycle thread ended on a create, "
                f"describe returned {gs} (expected 200) — settled state wrong — "
                f"Type4_StateLogicViolation — raw={graw[:200]}"
            )
        else:
            try:
                b = json.loads(graw)
                vec = ((((b or {}).get("result") or {}).get("config") or {})
                       .get("params") or {}).get("vectors")
                print(f"[settled] vectors={json.dumps(vec)[:200] if isinstance(vec, dict) else vec!r}")
                if isinstance(vec, dict) and (
                        vec.get("size") != 4 or vec.get("distance") != "Cosine"):
                    DEFECTS.append(
                        f"(settled) config corrupted by lifecycle race: "
                        f"vectors={vec!r} (expected size=4/Cosine) — "
                        f"Type4_StateLogicViolation"
                    )
            except (json.JSONDecodeError, ValueError, TypeError):
                print("OBSERVATION (settled): describe readback not JSON-parseable "
                      "— config check skipped")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
