#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_recover_004
# strategy: behavioral_contract
# endpoint: cluster+recover
# constraint_ids: qdrant_state_cluster_recover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency/State Blindness - a REFUSED cluster reset must not
#   still restart the peer or shed a single byte of local data; only an EXECUTED
#   recovery may restart, and even then "from local data" must hold)
"""
Attack: behavioral_contract (G4 both-direction, system-level state constraint) x
  constraints::qdrant_state_cluster_recover_001 (chunk_cluster+recover; POST
  /cluster/recover, URL from raw_knowledge api_endpoints[cluster+recover].url).
  The constraint promises: "recover removes the cluster metadata of the current
  peer and restarts it as a single-node cluster FROM LOCAL DATA; the operation is
  irrecoverable for removed peers". Both directions on this deployment:
  (negative/zero-trace face - the falsifiable one here) a REFUSED recover (4xx on
  the standalone face, per R6 lesson) must (a) NOT restart the peer - detected by
  a /healthz poller running through the whole call window, any non-200 probe is a
  restart blip - and (b) leave zero trace: describe config (vector size/distance,
  shards_number) unchanged, exact count and scroll payload readback identical,
  GET /cluster and GET /collections/{c}/cluster dispositions unchanged;
  (positive/destructive face) an EXECUTED 2xx may restart the peer (blip allowed,
  recorded as observation) but "from local data" still binds - data plane must be
  byte-identical after the op; data loss on either face = Type4. The true
  distributed destructive face (recover against a quorum-lost multi-node cluster)
  is SKIPPED: it needs a disposable cluster and is by-design destructive per the
  constraint/threat model - no conclusion is drawn on it.
  [chunk_cluster+recover coverage: behavioral_contract x
   qdrant_state_cluster_recover_001 (refused-reset zero-trace + restart-detector +
   local-data survival)]
Oracle: with the recover POST refused 4xx: /healthz poller (50ms cadence across
  the whole call window + 0.4s grace) sees ONLY 200 - any non-200 probe = the
  refused reset still restarted the peer = Type4_StateLogicViolation; describe
  config.vectors(size=4,distance=Cosine) + shards_number unchanged, exact
  count==3, scroll readback (ids+payloads) identical, GET /cluster and
  collection-cluster dispositions (status+description, time excluded) unchanged -
  any drift = Type4; 5xx with /healthz alive = Type3_RuntimeFailure; if executed
  2xx: restart blip allowed (observation), but identical data plane required,
  data loss = Type4

Rationale (G6): the restart side effect is the constraint's sharpest edge - a
refusal that still restarts the peer is state damage invisible to status-code
judging, so the poller makes it directly falsifiable; the payload/scroll readback
is the "from local data" promise made byte-level, and describe-config stability
catches a partial membership reset that survives a data-plane check.
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

# ---- runtime PATHS gap: register the contract-derived URL (raw_knowledge only) ----
RECOVER_KEY = "recover_peer"
if RECOVER_KEY not in rt.PATHS:
    rt.PATHS[RECOVER_KEY] = "/cluster/recover"
print(f"[path derivation] recover_peer = {rt.PATHS[RECOVER_KEY]} (raw_knowledge api_endpoints[cluster+recover].url)")

TS = str(int(time.time()))
COL = f"scrc4_{TS}_col"
POINTS = [
    {"id": 21, "vector": [0.1, 0.1, 0.1, 0.1], "payload": {"city": "rennes", "rank": 1}},
    {"id": 22, "vector": [0.3, 0.3, 0.3, 0.3], "payload": {"city": "nantes", "rank": 2}},
    {"id": 23, "vector": [0.5, 0.5, 0.5, 0.5], "payload": {"city": "lille", "rank": 3}},
]


def safe_request(method, path_key, body=None, path_params=None, query_params=None,
                timeout=30):
    """All HTTP through the runtime; kept in this exact call form so the inline
    liveness probes (GET healthz) stay visible to static checks. timeout is
    forwarded to rt.request (per-request transport timeout)."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def jload(raw):
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def result_node(raw):
    b = jload(raw)
    r = b.get("result") if isinstance(b, dict) else None
    return r


def script_error(msg):
    print(f"VERDICT: SCRIPT_ERROR - {msg}")
    sys.exit(2)


def defect(dtype, msg):
    print(f"VERDICT: DEFECT_FOUND ({dtype})")
    print(msg)
    sys.exit(1)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz")
    print(f"[{tag}] /healthz probe status={hs} raw={str(hraw)[:120]}")
    return hs


def disposition(path_key, path_params=None):
    """(status, description) of a face; volatile 'time' excluded."""
    st, raw = safe_request("GET", path_key, path_params=path_params, timeout=15)
    b = jload(raw)
    desc = b.get("description") if isinstance(b, dict) else None
    return st, (str(desc) if desc is not None else "")


def describe_stable():
    """Stable describe fields: vector config + shards_number (transient statuses
    like optimizer state are deliberately excluded)."""
    st, raw = safe_request("GET", "describe_collection",
                           path_params={"name": COL}, timeout=15)
    print(f"[describe] status={st} raw={str(raw)[:300]}")
    if st != 200:
        return None
    res = result_node(raw) or {}
    cfg = res.get("config") if isinstance(res, dict) else None
    vec = cfg.get("vectors") if isinstance(cfg, dict) else None
    if not isinstance(vec, dict):
        vec = {}
    return {
        "size": vec.get("size"),
        "distance": vec.get("distance"),
        "shards_number": res.get("shards_number") if isinstance(res, dict) else None,
    }


def scroll_snapshot():
    st, raw = safe_request("POST", "scroll",
                           body={"limit": 10, "with_payload": True},
                           path_params={"name": COL}, timeout=15)
    print(f"[scroll] status={st} raw={str(raw)[:300]}")
    if st != 200:
        return None
    res = result_node(raw) or {}
    pts = res.get("points") if isinstance(res, dict) else None
    if not isinstance(pts, list):
        return None
    return sorted([(p.get("id"), json.dumps(p.get("payload"), sort_keys=True))
                   for p in pts if isinstance(p, dict)])


def exact_count():
    st, raw = safe_request("POST", "count", body={"exact": True},
                           path_params={"name": COL}, timeout=15)
    print(f"[count] status={st} raw={str(raw)[:200]}")
    if st != 200:
        return None
    res = result_node(raw)
    return res.get("count") if isinstance(res, dict) else None


def face_guard():
    """R6 lesson: probe the deployment face first; judge only the falsifiable
    status class; exit honestly otherwise."""
    st, desc = disposition("cluster_status")
    print(f"[face probe GET /cluster] status={st} description={desc[:200]}")
    if st == 0:
        liveness("transport")
        script_error("transport failure probing GET /cluster; no defect conclusion")
    if 500 <= st <= 599:
        hs = liveness("5xx")
        if hs != 200:
            script_error(f"GET /cluster 5xx ({st}) and /healthz {hs}; deployment unstable")
        script_error(f"GET /cluster 5xx ({st}) with /healthz alive; face state unknown - no falsifiable leg")
    if 200 <= st < 300:
        print("SKIPPED: POST /cluster/recover on a live distributed deployment - the constraint "
              "qdrant_state_cluster_recover_001 marks recovery as irrecoverable-destructive for "
              "removed peers (by-design per threat_model); exercising the destructive face needs "
              "a disposable multi-node cluster")
        script_error("distributed deployment detected (GET /cluster 200); destructive recover face "
                     "not exercisable on the shared deployment; honest exit (R6 lesson)")
    if 400 <= st < 500:
        return True
    script_error(f"unexpected GET /cluster status {st}; no defect conclusion")


def cleanup():
    try:
        rt.drop_collection(COL)
    except Exception:
        pass  # cleanup failures are non-fatal


def main():
    hs, _ = safe_request("GET", "healthz")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")
    print(f"[pre-probe] /healthz status={hs}")
    face_guard()

    try:
        # ---- witness + baseline state snapshot ----
        ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {COL}: {err}")
        st, raw = safe_request("PUT", "upsert_points", body={"points": POINTS},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=20)
        print(f"[witness upsert] status={st} raw={str(raw)[:200]}")
        if st not in (200, 201):
            script_error(f"witness upsert failed ({st}); no defect conclusion")

        base_desc = describe_stable()
        base_scroll = scroll_snapshot()
        base_count = exact_count()
        base_cluster = disposition("cluster_status")
        base_cc = disposition("collection_cluster", path_params={"name": COL})
        print(f"[baseline] describe={json.dumps(base_desc)} count={base_count} "
              f"cluster=({base_cluster[0]}, {base_cluster[1][:80]}) "
              f"collection_cluster=({base_cc[0]}, {base_cc[1][:80]})")
        if base_desc is None or base_scroll is None or base_count != 3:
            script_error("baseline state not established; no defect conclusion")

        # ---- restart detector: /healthz poller across the whole call window ----
        stop = threading.Event()
        probes = []

        def poller():
            while not stop.is_set():
                s, _ = safe_request("GET", "healthz", timeout=2)
                probes.append(s)
                stop.wait(0.05)

        th = threading.Thread(target=poller, daemon=True)
        th.start()

        # ---- the recover POST under observation ----
        st, raw = safe_request("POST", RECOVER_KEY, timeout=30)
        time.sleep(0.4)  # grace: a restart triggered mid-call surfaces right after
        stop.set()
        th.join(timeout=5)

        print(f"[POST /cluster/recover] status={st} raw={str(raw)[:400]}")
        print(f"[poller] {len(probes)} healthz probes, statuses={sorted(set(probes))}")
        blips = [s for s in probes if s != 200]
        refused = 400 <= st < 500
        executed = 200 <= st < 300

        if st == 0:
            liveness("transport")
            script_error("transport failure on POST /cluster/recover; no defect conclusion")
        if 500 <= st <= 599:
            hs = liveness("5xx")
            if hs != 200:
                script_error(f"5xx on recover and /healthz not 200 (={hs}); no defect conclusion")
            defect("Type3_RuntimeFailure",
                   f"POST /cluster/recover raised {st} while /healthz is alive - constraint "
                   f"qdrant_state_cluster_recover_001 expects a reset or a clean refusal, "
                   f"never a crash; raw={str(raw)[:200]}")
        if not refused and not executed:
            script_error(f"unexpected recover status {st}; no defect conclusion")
        if not probes:
            script_error("poller collected no healthz probes; restart detection unavailable")

        if refused and blips:
            defect("Type4_StateLogicViolation",
                   f"a REFUSED recover ({st}) still took the peer down mid-call: {len(blips)}/{len(probes)} "
                   f"/healthz probes missed 200 (statuses {sorted(set(blips))}) - the constraint's "
                   f"restart side effect leaked through the refusal path")
        if executed and blips:
            print(f"OBSERVATION: executed recover ({st}) restarted the peer ({len(blips)}/{len(probes)} "
                  f"healthz probes missed) - allowed by the constraint, recorded")

        # ---- post-state reconciliation (both faces: local data must survive) ----
        hs = liveness("reconcile")
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"/healthz returned {hs} after POST /cluster/recover (status {st}) - the "
                   f"peer must stay alive through a refused or executed recovery")

        now_desc = describe_stable()
        now_scroll = scroll_snapshot()
        now_count = exact_count()
        print(f"[reconcile] describe={json.dumps(now_desc)} count={now_count} "
              f"scroll={json.dumps(now_scroll)[:200]}")
        if now_desc != base_desc:
            defect("Type4_StateLogicViolation",
                   f"describe config drifted across POST /cluster/recover (status {st}): "
                   f"{json.dumps(base_desc)} -> {json.dumps(now_desc)} - membership/reset "
                   f"state leaked into the witness collection config")
        if now_count != base_count or now_scroll != base_scroll:
            defect("Type4_StateLogicViolation",
                   f"local data did not survive POST /cluster/recover (status {st}): count "
                   f"{base_count}->{now_count}, scroll {json.dumps(base_scroll)[:120]} -> "
                   f"{json.dumps(now_scroll)[:120]} - the constraint binds BOTH faces with "
                   f"'restarts ... FROM LOCAL DATA'")

        if refused:
            now_cluster = disposition("cluster_status")
            now_cc = disposition("collection_cluster", path_params={"name": COL})
            print(f"[reconcile faces] cluster=({now_cluster[0]}, {now_cluster[1][:80]}) "
                  f"collection_cluster=({now_cc[0]}, {now_cc[1][:80]})")
            if now_cluster != base_cluster or now_cc != base_cc:
                defect("Type4_StateLogicViolation",
                       f"cluster-face disposition drifted across a REFUSED recover: "
                       f"/cluster {base_cluster[0]}->{now_cluster[0]}, collection-cluster "
                       f"{base_cc[0]}->{now_cc[0]} - a refused reset must leave zero trace")

        print("SKIPPED: the true destructive face (recover against a quorum-lost multi-node "
              "cluster, verifying the reset-to-single-node transition itself) - by-design "
              "destructive per threat_model; needs a disposable cluster, no conclusion drawn")
        print(f"[summary] recover status={st} ({'refused' if refused else 'executed'}); "
              f"restart detector clean={'yes' if not blips else 'no'}; state fully reconciled")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
