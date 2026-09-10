#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_recover_002
# strategy: upsert_idempotence
# endpoint: cluster+recover
# constraint_ids: qdrant_state_cluster_recover_001, qdrant_behavioral_cluster_recover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (operational idempotence / disposition stability, G6: the
  mutation point is repetition of a state-machine-destructive op — the second
  and third execution of a metadata-removal op are exactly where a partially
  idempotent implementation is most likely to flip disposition or leak state)
  on POST /cluster/recover (URL from raw_knowledge api_endpoints[].url,
  registered into rt.PATHS). Three IDENTICAL bodyless POST /cluster/recover
  calls run sequentially against a deployment with a live data-plane anchor
  (unique-prefix collection, 6 points, exact count baseline). Judged per call
  and across the sequence: (1) disposition family stability — identical
  requests must land in one family {2xx, 4xx, 5xx, transport}; a 4xx-then-2xx
  (or 2xx-then-4xx) flip on an unchanged environment is
  Type4_StateLogicViolation (G9: same request, inconsistent disposition);
  any 5xx = Type3_RuntimeFailure only after /healthz liveness; (2) after the
  whole sequence the data plane must be intact: describe 200, exact count ==
  6, GET /cluster 200, /healthz 200 — drift = Type4 (repetition must not be
  cumulative destruction beyond the single documented op semantics).
  Standalone "Distributed mode disabled" 4xx masks recorded as OBSERVATION per
  the R6 lesson; the family-stability and no-cumulative-damage legs remain the
  falsifiable core. A 2xx recover legitimately restarts consensus, so a
  bounded grace liveness window runs after each accepted call.
  [chunk_cluster+recover coverage: upsert_idempotence x
   qdrant_state_cluster_recover_001 (destructive-op repetition leaves data
   plane intact) + qdrant_behavioral_cluster_recover_001 (identical-request
   disposition stability across the 2xx/4xx faces)]
Oracle: three identical POST /cluster/recover calls -> all three statuses in
  ONE family (all 2xx or all 400..499; any family flip =
  Type4_StateLogicViolation; any 500..599 = Type3_RuntimeFailure only after
  /healthz returns 200); after the sequence: /healthz 200 within the 20s
  grace window (never-200 = Type3), GET /collections/{c} -> 200 (404 =
  Type4_StateLogicViolation), exact count == 6 (count != 6 =
  Type4_StateLogicViolation), GET /cluster -> 200 (5xx = Type3 only after
  liveness).
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


def load_recover_template():
    """Standing lesson: URL only from raw_knowledge api_endpoints[].url."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == "cluster+recover" and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
    return None


_RECOVER_TPL = load_recover_template()
if not _RECOVER_TPL:
    print("VERDICT: SCRIPT_ERROR - cluster+recover url not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
rt.PATHS["cluster_recover"] = _RECOVER_TPL
print(f"[url-derived] cluster+recover -> {_RECOVER_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, path_params=None, body=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; forwards timeout/path_params/body/
    query_params exactly as call sites use them (R6 lesson)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


GRACE_S = 20
REPEATS = 3


def exact_count(name):
    """POST count exact=true -> (status, count|None, raw); envelope result.<field>."""
    s, raw = safe_request("POST", "count", path_params={"name": name},
                          body={"exact": True})
    if s != 200:
        return s, None, raw
    try:
        b = json.loads(raw) if raw else {}
        node = b.get("result") if isinstance(b, dict) else None
        if isinstance(node, dict) and isinstance(node.get("count"), int):
            return s, node["count"], raw
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return s, None, raw


def upsert_wait(name, points):
    """PUT upsert with wait=true (wait is a URL query param on qdrant)."""
    return safe_request("PUT", "upsert_points", path_params={"name": name},
                        body={"points": points}, query_params={"wait": "true"})


def grace_liveness(seconds):
    """Poll /healthz up to `seconds`; True once 200."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        hs, _hraw = safe_request("GET", "healthz")
        if hs == 200:
            return True
        time.sleep(1.0)
    return False


def family(status):
    """Collapse a status to a disposition family label."""
    if 200 <= status < 300:
        return "2xx"
    if 400 <= status <= 499:
        return "4xx"
    if 500 <= status <= 599:
        return "5xx"
    if status == 0:
        return "transport"
    return f"s{status}"


def liveness_ok():
    """Inline /healthz probe (exact call form kept visible)."""
    hs, hraw = safe_request("GET", "healthz")
    print(f"[healthz] probe status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "screc2_" + TS + "_"
    C = PFX + "col"
    N = 6
    DIM = 4
    DEFECTS = []

    try:
        # ---- reachability probes ----
        if not liveness_ok():
            print("ENV_ISSUE: /healthz not 200 at probe — service not exercisable")
            return "SCRIPT_ERROR"
        cs0, craw0 = safe_request("GET", "cluster_status")
        print(f"[probe GET /cluster] status={cs0} raw={craw0[:200]}")
        if cs0 == 0 or 500 <= cs0 <= 599:
            print(f"ENV_ISSUE: GET /cluster returned {cs0} — cluster face not exercisable")
            return "SCRIPT_ERROR"

        # ---- data-plane anchor ----
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [0.1 * (i + 1), 0.2, 0.3, 0.4],
                "payload": {"batch": "seed"}} for i in range(N)]
        s, raw = upsert_wait(C, pts)
        print(f"[seed upsert wait=true] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR seed upsert {s}: {raw[:200]}")
            return "SCRIPT_ERROR"
        sc, n0, craw_c = exact_count(C)
        print(f"[baseline exact count] status={sc} count={n0} raw={craw_c[:200]}")
        if sc != 200 or n0 != N:
            print(f"SETUP_ERROR baseline count status={sc} count={n0} (expected {N})")
            return "SCRIPT_ERROR"

        # ---- three identical recover calls: disposition stability ----
        statuses = []
        for i in range(REPEATS):
            s, raw = safe_request("POST", "cluster_recover")
            statuses.append(s)
            print(f"[recover #{i + 1}] status={s} raw={raw[:300]}")
            if 500 <= s <= 599:
                if not liveness_ok():
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"recover call #{i + 1} returned {s} (5xx; service alive "
                    f"per /healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
                )
            elif 400 <= s <= 499 and "distributed" in str(raw).lower():
                print(f"OBSERVATION (mask, call #{i + 1}): 4xx looks like the "
                      f"standalone distributed-mode gate — recorded, family "
                      f"stability still judged")
            elif 200 <= s < 300:
                # accepted recover legitimately restarts consensus -> grace
                if not grace_liveness(GRACE_S):
                    DEFECTS.append(
                        f"after accepted recover call #{i + 1} /healthz never "
                        f"returned 200 within {GRACE_S}s — service left down "
                        f"by the documented op — Type3_RuntimeFailure"
                    )
                    break
            elif s == 0:
                if not grace_liveness(GRACE_S):
                    DEFECTS.append(
                        f"recover call #{i + 1} transport-failed AND /healthz "
                        f"never returned 200 within {GRACE_S}s — Type3_RuntimeFailure"
                    )
                    break

        fams = sorted({family(x) for x in statuses})
        print(f"[disposition families] statuses={statuses} families={fams}")
        if len(fams) > 1:
            DEFECTS.append(
                f"three IDENTICAL POST /cluster/recover requests on an "
                f"unchanged environment landed in different disposition "
                f"families {fams} (statuses={statuses}) — same request, "
                f"inconsistent disposition — Type4_StateLogicViolation"
            )

        # ---- post-sequence data-plane integrity ----
        if statuses and not grace_liveness(GRACE_S):
            DEFECTS.append(
                f"after the recover sequence /healthz never returned 200 "
                f"within {GRACE_S}s — Type3_RuntimeFailure"
            )
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        ds, draw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[post-sequence describe] status={ds} raw={draw[:200]}")
        if ds == 404:
            DEFECTS.append(
                f"GET /collections/{C} returned 404 after {len(statuses)} "
                f"recover calls (statuses={statuses}) — repetition cumulatively "
                f"destroyed collection state — Type4_StateLogicViolation"
            )
        elif ds == 0 or 500 <= ds <= 599:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"describe after recover sequence returned {ds} (200 expected; "
                f"service alive per /healthz) — Type3_RuntimeFailure — "
                f"raw={draw[:200]}"
            )

        sc2, n1, craw2 = exact_count(C)
        print(f"[post-sequence exact count] status={sc2} count={n1} raw={craw2[:200]}")
        if sc2 == 200 and n1 is not None and n1 != N:
            DEFECTS.append(
                f"exact count after the recover sequence is {n1}, expected "
                f"{N} — repetition altered local data — "
                f"Type4_StateLogicViolation"
            )

        cs2, craw3 = safe_request("GET", "cluster_status")
        print(f"[post-sequence GET /cluster] status={cs2} raw={craw3[:200]}")
        if cs2 == 0 or 500 <= cs2 <= 599:
            if not liveness_ok():
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"GET /cluster after the recover sequence returned {cs2} "
                f"(200 expected; service alive per /healthz) — "
                f"Type3_RuntimeFailure — raw={craw3[:200]}"
            )

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
