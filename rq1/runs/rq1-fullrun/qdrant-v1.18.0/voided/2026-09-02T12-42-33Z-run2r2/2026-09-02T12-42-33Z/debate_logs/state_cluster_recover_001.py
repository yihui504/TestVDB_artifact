#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_recover_001
# strategy: delete_consistency
# endpoint: cluster+recover
# constraint_ids: qdrant_state_cluster_recover_001, qdrant_behavioral_cluster_recover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-destructive-op state consistency) on POST /cluster/recover
  (cluster+recover; URL read verbatim from raw_knowledge api_endpoints[].url,
  registered into rt.PATHS so rt.request stays the single HTTP exit). The state
  constraint qdrant_state_cluster_recover_001 declares recover destructive for
  cluster membership state but PRESERVING for local data ("restarts as a
  single-node cluster from local data"); the behavioral assertion
  qdrant_behavioral_cluster_recover_001 documents the 200 face. Reachability
  probes first (R5/R6 lesson): /healthz + GET /cluster snapshot; transport or
  health failures exit honestly with SCRIPT_ERROR. Sequence: create collection
  (unique prefix screc1_) -> upsert N=8 points wait=true -> exact count == 8
  (positive control, G4) -> fire the bodyless POST /cluster/recover ->
  status-class disposition -> data-plane re-read: describe must stay 200, exact
  count must stay 8, GET /cluster face must stay 200, /healthz must stay 200.
  A REFUSED (4xx) recover that mutates the data plane is Type4_StateLogicViolation
  (refused op must be a no-op); an ACCEPTED (2xx) recover that loses local data
  violates the constraint's own "from local data" wording = Type4; 5xx =
  Type3_RuntimeFailure only after /healthz liveness; a recover after which
  /healthz never returns 200 within a bounded restart grace window is Type3.
  Standalone "Distributed mode disabled" 4xx masks are recorded as OBSERVATION
  (the refusal satisfies the not-applicable face at the status level; the
  no-op consistency legs are still judged — that is exactly what is falsifiable
  on this deployment per the R6 lesson).
  [chunk_cluster+recover coverage: delete_consistency x
   qdrant_state_cluster_recover_001 (local-data-preservation clause +
   refused-op-is-a-no-op clause) + the 2xx/4xx/5xx disposition faces of
   qdrant_behavioral_cluster_recover_001]
Oracle: after POST /cluster/recover: /healthz returns 200 within the
  GRACE_S (=20s) restart grace window (never-200 = Type3_RuntimeFailure);
  GET /collections/{c} -> HTTP 200 and exact count == 8 (404 or count != 8 =
  Type4_StateLogicViolation; 5xx on these faces while /healthz is 200 =
  Type3_RuntimeFailure); GET /cluster -> HTTP 200 (5xx = Type3 only after
  /healthz liveness); the recover call itself: 2xx and 4xx are both recordable
  dispositions, 5xx = Type3 only after /healthz liveness, transport-0 that
  outlives the grace window = Type3_RuntimeFailure.
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
    """Standing lesson: derive the URL only from raw_knowledge
    api_endpoints[].url (entry with path == "cluster+recover"). No literal
    path invented."""
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
# register derived template so the path_key lives inside rt.PATHS (whitelist
# honored; rt.request stays the single HTTP exit with runtime auth/base handling)
rt.PATHS["cluster_recover"] = _RECOVER_TPL
print(f"[url-derived] cluster+recover -> {_RECOVER_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, path_params=None, body=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; signature forwards timeout/path_params/
    body/query_params exactly as call sites use them (R6 lesson). Inline
    liveness probes (GET healthz) stay in this exact call form for
    static-check visibility."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


GRACE_S = 20  # bounded restart grace: a 2xx recover legitimately restarts consensus


def exact_count(name):
    """POST count exact=true -> (status, count|None, raw). Envelope
    result.<field> per standing lesson."""
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
    """PUT upsert with wait=true (wait is a URL query param on qdrant — never
    stuffed into the body; runtime docstring v34 R1 S1 lesson)."""
    return safe_request("PUT", "upsert_points", path_params={"name": name},
                        body={"points": points}, query_params={"wait": "true"})


def grace_liveness(seconds):
    """Restart-grace WAIT loop (not the transport-failure liveness probe —
    that one is inlined in each failure branch per the R6 peer_delete fix)."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        hs, _hraw = safe_request("GET", "healthz")
        if hs == 200:
            return True
        time.sleep(1.0)
    return False


def settle_read(fn, tries=5, delay=1.0):
    """Bounded retry for transient 0/5xx on read faces while a legitimate
    restart may be in flight. Returns the last (status, ...) result."""
    result = fn()
    for _ in range(tries - 1):
        ok_flag = result[0] == 200
        if ok_flag:
            return result
        time.sleep(delay)
        result = fn()
    return result


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "screc1_" + TS + "_"
    C = PFX + "col"
    N = 8
    DIM = 4
    DEFECTS = []

    try:
        # ---- reachability probes (R5/R6: probe first, exit honestly) ----
        hs, hraw = safe_request("GET", "healthz")
        print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            print("ENV_ISSUE: /healthz not 200 at probe — service not exercisable")
            return "SCRIPT_ERROR"
        cs, craw = safe_request("GET", "cluster_status")
        print(f"[probe GET /cluster] status={cs} raw={craw[:200]}")
        if cs == 0 or 500 <= cs <= 599:
            print(f"ENV_ISSUE: GET /cluster returned {cs} — cluster face not exercisable")
            return "SCRIPT_ERROR"

        # ---- setup: collection + N points + positive-control count ----
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

        # ---- fire the destructive op (bodyless per contract params) ----
        s, raw = safe_request("POST", "cluster_recover")
        print(f"[POST /cluster/recover] status={s} raw={raw[:300]}")
        if 200 <= s < 300:
            print("OBSERVATION: recover accepted (2xx) on this deployment — "
                  "the strong from-local-data preservation legs below apply")
            try:
                b = json.loads(raw) if raw else {}
                if isinstance(b, dict):
                    print(f"[envelope observation] result={b.get('result')!r} "
                          f"status={b.get('status')!r} time={b.get('time')!r} "
                          f"(endpoint response_shape: result boolean, status "
                          f"string, time number)")
            except (json.JSONDecodeError, ValueError, TypeError):
                print("OBSERVATION: 2xx body not JSON — envelope not inspectable")
        elif 400 <= s <= 499:
            if "distributed" in str(raw).lower():
                print("OBSERVATION (mask): 4xx looks like the standalone "
                      "distributed-mode gate — refused at the status level; "
                      "no-op consistency legs still judged")
            else:
                print(f"[recover] refused with {s} — refusal recorded")
        elif 500 <= s <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"POST /cluster/recover returned {s} (5xx; service alive per "
                f"/healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
        elif s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            print("OBSERVATION: transport-level result on recover while "
                  "/healthz answers 200 — restart grace window below still "
                  "guards the attributable-death case")

        # ---- grace liveness: a 2xx recover legitimately restarts consensus ----
        if not grace_liveness(GRACE_S):
            DEFECTS.append(
                f"after POST /cluster/recover (status={s}) /healthz never "
                f"returned 200 within the {GRACE_S}s grace window — the "
                f"documented recover op left the service down — "
                f"Type3_RuntimeFailure"
            )
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"

        # ---- data-plane leg: describe must stay 200 (404 = data destroyed) ----
        ds, draw = settle_read(lambda: safe_request("GET", "describe_collection",
                                                    path_params={"name": C}))
        print(f"[post-recover describe] status={ds} raw={draw[:200]}")
        if ds == 404:
            DEFECTS.append(
                f"GET /collections/{C} returned 404 after POST /cluster/recover "
                f"(status={s}) — a refused recover must be a no-op and an "
                f"accepted one restarts 'from local data' — collection state "
                f"destroyed — Type4_StateLogicViolation"
            )
        elif ds == 0 or 500 <= ds <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"describe after recover returned {ds} (200 expected; service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={draw[:200]}"
            )

        # ---- count leg: exact count must stay N ----
        sc2, n1, craw2 = settle_read(lambda: exact_count(C))
        print(f"[post-recover exact count] status={sc2} count={n1} raw={craw2[:200]}")
        if sc2 == 200 and n1 is not None and n1 != N:
            DEFECTS.append(
                f"exact count after POST /cluster/recover (status={s}) is {n1}, "
                f"expected {N} — local data altered by the recover face — "
                f"Type4_StateLogicViolation"
            )
        elif (sc2 == 0 or 500 <= sc2 <= 599) and not ds == 404:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"count after recover returned {sc2} (200 expected; service "
                f"alive per /healthz) — Type3_RuntimeFailure — raw={craw2[:200]}"
            )

        # ---- cluster-face leg: GET /cluster must stay 200 ----
        cs2, craw3 = settle_read(lambda: safe_request("GET", "cluster_status"))
        print(f"[post-recover GET /cluster] status={cs2} raw={craw3[:200]}")
        if cs2 == 0 or 500 <= cs2 <= 599:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[healthz] /healthz probe status={hs} raw={str(hraw)[:120]}")
            if hs != 200:
                return "SCRIPT_ERROR"
            DEFECTS.append(
                f"GET /cluster after recover returned {cs2} (200 expected; "
                f"service alive per /healthz) — cluster-status face degraded "
                f"by the recover call — Type3_RuntimeFailure — raw={craw3[:200]}"
            )
        elif cs2 == 200 and craw != craw3:
            print(f"OBSERVATION: GET /cluster body changed across recover "
                  f"(before={craw[:120]} after={craw3[:120]}) — membership-state "
                  f"change on a documented-as-destructive op is expected only "
                  f"on the accepted face; recorded, data-plane legs carry the "
                  f"defect judgment")

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
