#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_recover_001
# strategy: behavioral_contract
# endpoint: cluster+recover
# constraint_ids: qdrant_behavioral_cluster_recover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-03 (Concurrency/State Blindness - a refused/executed dangerous op must
#   leave the data plane and the cluster face fully reconciled) + BS-05 (Documentation
#   Drift - the documented "200 ok" face vs the disabled-deployment face actually served)
"""
Attack: behavioral_contract (G4 both-direction) x
  assertions::qdrant_behavioral_cluster_recover_001 (chunk_cluster+recover; POST
  /cluster/recover, URL from raw_knowledge api_endpoints[cluster+recover].url).
  The assertion promises "HTTP 200 on cluster recovery (dangerous operational op)",
  and the sibling constraint qdrant_state_cluster_recover_001 marks the op as a
  destructive single-node reset "meant for permanently-lost quorum". Both directions
  on this deployment: (positive face) if the endpoint executes (2xx), the documented
  200 must come with a coherent post-state - data plane preserved ("restart from
  local data"), /healthz alive, and the /cluster face either consistently disabled
  or consistently deployed (a 200 on recover while GET /cluster still refuses with
  the disabled diagnostic is a G9 inconsistent disposition across the distributed
  face family); (negative face) if the deployment disables the face (expected per
  R6 lesson: standalone deployment refuses distributed faces with 4xx "Distributed
  mode disabled"), the refusal must be a clean 4xx - never 5xx/crash - and the
  refusal must leave zero trace on data plane and cluster state (Type4 on drift).
  [chunk_cluster+recover coverage: behavioral_contract x
   qdrant_behavioral_cluster_recover_001 (documented-200 face + refusal class +
   full reconciliation)]
Oracle: on the disabled face POST /cluster/recover -> 4xx refusal (2xx = judged on
  the coherent-post-state rule: data intact + healthz 200 + /cluster face
  disposition consistent with the executed recovery, else Type4_StateLogicViolation;
  /cluster still "disabled" after an executed 200 = G9 inconsistency = Type4);
  5xx with /healthz alive = Type3_RuntimeFailure; after the leg: /healthz=200,
  witness collection still listed, exact count==3, scroll readback (ids+payloads)
  identical, GET /cluster disposition (status+description, volatile time excluded)
  unchanged - any drift = Type4_StateLogicViolation

Rationale (G6): the single POST /cluster/recover is the maximal breaker available
for this chunk - it is the one call the contract itself labels destructive; on a
standalone deployment the only falsifiable forms are the refusal class (clean 4xx
vs crash) and post-op reconciliation (zero trace), both of which are exactly the
promise surfaces the assertion + sibling state constraint declare.
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
COL = f"scrc1_{TS}_col"
POINTS = [
    {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"city": "paris", "rank": 1}},
    {"id": 2, "vector": [0.5, 0.6, 0.7, 0.8], "payload": {"city": "lyon", "rank": 2}},
    {"id": 3, "vector": [0.9, 1.0, 1.1, 1.2], "payload": {"city": "nice", "rank": 3}},
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


def cluster_disposition():
    """(status, description) of the distributed face; volatile 'time' excluded."""
    st, raw = safe_request("GET", "cluster_status", timeout=15)
    b = jload(raw)
    desc = b.get("description") if isinstance(b, dict) else None
    return st, (str(desc) if desc is not None else "")


def face_guard():
    """R6 lesson: probe the deployment face first; judge only the falsifiable
    status class; exit honestly otherwise."""
    st, desc = cluster_disposition()
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
        print("SKIPPED: POST /cluster/recover on a live distributed deployment - sibling constraint "
              "qdrant_state_cluster_recover_001 marks recovery as destructive for cluster membership "
              "(by-design per threat_model); exercising it needs a disposable cluster")
        script_error("distributed deployment detected (GET /cluster 200); destructive recover face "
                     "not exercisable on the shared deployment; honest exit (R6 lesson)")
    if 400 <= st < 500:
        return True
    script_error(f"unexpected GET /cluster status {st}; no defect conclusion")


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
        # ---- witness collection + deterministic data plane ----
        ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {COL}: {err}")
        st, raw = safe_request("PUT", "upsert_points", body={"points": POINTS},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=20)
        print(f"[witness upsert] status={st} raw={str(raw)[:200]}")
        if st not in (200, 201):
            script_error(f"witness upsert failed ({st}); no defect conclusion")

        base_count = exact_count()
        base_scroll = scroll_snapshot()
        base_disp = cluster_disposition()
        print(f"[baseline] count={base_count} scroll={json.dumps(base_scroll)[:200]} "
              f"cluster=({base_disp[0]}, {base_disp[1][:120]})")
        if base_count != 3 or base_scroll is None:
            script_error("baseline data plane not established; no defect conclusion")

        # ---- the single recover POST: the chunk's core probe ----
        st, raw = safe_request("POST", RECOVER_KEY, timeout=20)
        print(f"[POST /cluster/recover] status={st} raw={str(raw)[:400]}")

        if st == 0:
            liveness("transport")
            script_error("transport failure on POST /cluster/recover; no defect conclusion")

        if 500 <= st <= 599:
            hs = liveness("5xx")
            if hs != 200:
                script_error(f"5xx on recover and /healthz not 200 (={hs}); no defect conclusion")
            defect("Type3_RuntimeFailure",
                   f"POST /cluster/recover raised server error {st} while /healthz is "
                   f"alive; assertion qdrant_behavioral_cluster_recover_001 expects a documented "
                   f"200 (or a clean face refusal on standalone), never a crash; raw={str(raw)[:200]}")

        executed_200 = 200 <= st < 300

        # ---- reconciliation (both branches) ----
        hs = liveness("reconcile")
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"/healthz returned {hs} after POST /cluster/recover (status {st}) - the "
                   f"deployment must stay alive through a refused or executed recovery")

        lst, lraw = safe_request("GET", "list_collections", timeout=15)
        print(f"[reconcile list] status={lst} raw={str(lraw)[:300]}")
        names = []
        if lst == 200:
            res = result_node(lraw) or {}
            cols = res.get("collections") if isinstance(res, dict) else None
            if isinstance(cols, list):
                names = [c.get("name") for c in cols if isinstance(c, dict)]
        if lst != 200 or COL not in names:
            defect("Type4_StateLogicViolation",
                   f"witness collection {COL} missing from GET /collections after recover "
                   f"(status {st}) - the op promised 'restart from local data', data loss instead")

        now_count = exact_count()
        now_scroll = scroll_snapshot()
        print(f"[reconcile data] count={now_count} scroll={json.dumps(now_scroll)[:200]}")
        if now_count != base_count or now_scroll != base_scroll:
            defect("Type4_StateLogicViolation",
                   f"data plane drifted across POST /cluster/recover (status {st}): count "
                   f"{base_count}->{now_count}, scroll {json.dumps(base_scroll)[:120]} -> "
                   f"{json.dumps(now_scroll)[:120]} - local data must survive a refused or "
                   f"executed recovery")

        now_disp = cluster_disposition()
        print(f"[reconcile cluster] disposition=({now_disp[0]}, {now_disp[1][:120]})")
        if executed_200:
            # documented 200 face: the post-state must be COHERENT, not still-disabled
            if now_disp[0] == base_disp[0] and now_disp[1] == base_disp[1] \
                    and 400 <= now_disp[0] < 500:
                defect("Type4_StateLogicViolation",
                       f"G9 inconsistent disposition: POST /cluster/recover executed 200 while the "
                       f"sibling distributed face GET /cluster still refuses {now_disp[0]} "
                       f"'{now_disp[1][:120]}' - one face executed a cluster reset the other face "
                       f"claims is impossible; raw={str(raw)[:200]}")
            print("[summary] recover executed 200 with coherent post-state and intact data plane")
        else:
            if 400 <= st < 500:
                if now_disp != base_disp:
                    defect("Type4_StateLogicViolation",
                           f"GET /cluster disposition changed across a REFUSED recover "
                           f"({base_disp[0]}/{base_disp[1][:80]} -> {now_disp[0]}/{now_disp[1][:80]})"
                           f" - a refused op must leave zero trace")
                print("[summary] disabled face refused cleanly (4xx) + full reconciliation clean")
            else:
                script_error(f"unexpected recover status {st}; no defect conclusion")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()



if __name__ == "__main__":
    main()
