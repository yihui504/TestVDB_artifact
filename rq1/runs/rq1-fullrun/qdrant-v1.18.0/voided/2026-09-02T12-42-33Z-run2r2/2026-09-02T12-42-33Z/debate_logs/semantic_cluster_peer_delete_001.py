#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_peer_delete_001
# strategy: behavioral_contract
# endpoint: cluster+peer+delete
# constraint_ids: qdrant_behavioral_cluster_peer_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/remove-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - is the documented 4xx-on-invalid-peer-id disposition actually delivered?)
"""
Attack: behavioral_contract x assertions::qdrant_behavioral_cluster_peer_delete_001
  (chunk_cluster+peer+delete; DELETE /cluster/peer/{peer_id}, URL from raw_knowledge
  api_endpoints[cluster+peer+delete].url). Negative-face disposition matrix over four
  well-formed u64 peer ids that are provably not live cluster peers (GET /cluster
  exposes the peer inventory; ids found there are excluded from the battery). The
  documented positive face ("valid peer removal returns HTTP 200") has no exercisable
  subject on this deployment - a single node whose cluster status reports disabled has
  no removable peer that is not simultaneously the destructive "last peer" case
  (that face is attacked with a safety guard in semantic_cluster_peer_delete_005
  against the state constraint); it is annotated here as an OBSERVATION, not judged.
  [chunk_cluster+peer+delete coverage: behavioral_contract x
   qdrant_behavioral_cluster_peer_delete_001 (4xx-on-invalid-peer-id leg)]
Oracle: every non-live well-formed peer id -> HTTP 4xx (400/404/422 all satisfy the
  documented "4xx on invalid peer id"); any 2xx = Type1_IllegalSuccess (destructive
  op claims success on a non-existent peer), any 5xx with /healthz alive = Type3,
  transport failure (status 0) = SCRIPT_ERROR after an inline /healthz probe
  (assertion qdrant_behavioral_cluster_peer_delete_001)

Rationale (G6): peer_id existence is the single hinge the documented disposition
swings on for this endpoint - there is no body, no filter, no other parameter that
can flip the verdict, so ghost ids with maximum u64 spread (0, 1, random-large,
u64-max) are the strongest breakers of the 4xx promise. Same-shape family
generalization (G3): one id is not evidence; four spread ids keep a
single-id quirk (e.g. 0 treated as "self") from masking the family behavior.
"""

import os
import sys
import json
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

# ---- runtime PATHS gap: the peer-delete route is not in runtime PATHS (the module
# predates this chunk). Register the contract-derived URL so ALL HTTP still exits
# through rt.request (single exit, query params supported). URL template is
# raw_knowledge api_endpoints[cluster+peer+delete].url, never invented. ----
REMOVE_PEER_KEY = "remove_peer"
if REMOVE_PEER_KEY not in rt.PATHS:
    rt.PATHS[REMOVE_PEER_KEY] = "/cluster/peer/{peer_id}"
print(f"[path derivation] remove_peer = {rt.PATHS[REMOVE_PEER_KEY]} (raw_knowledge api_endpoints[cluster+peer+delete].url)")

FACE_UNREACHABLE = "FACE_UNREACHABLE"


def safe_request(method, path_key, path_params=None, body=None, query_params=None,
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
    return r if isinstance(r, dict) else None


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


def classify_probe(status, raw, ctx):
    """Declared expectation first, then compare (G7). Returns True on a clean 4xx
    refusal; exits the process on 2xx / 5xx / transport; returns FACE_UNREACHABLE
    sentinel on 405 (method face not exposed by this deployment)."""
    print(f"[{ctx}] status={status} raw={str(raw)[:300]}")
    if status == 0:
        liveness("transport")
        script_error(f"transport failure on {ctx} (status=0); no defect conclusion")
    if 500 <= status <= 599:
        hs = liveness("5xx")
        if hs != 200:
            script_error(f"5xx on {ctx} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"removal of a non-live peer id ({ctx}) raised a server error {status} while "
               f"/healthz is alive; documented disposition is 4xx; raw={str(raw)[:200]}")
    if 200 <= status < 300:
        defect("Type1_IllegalSuccess",
               f"assertion promises 4xx on an invalid peer id; {ctx} got {status} with a success "
               f"payload - a destructive op claims success on a non-existent peer; raw={str(raw)[:200]}")
    if status == 405:
        print(f"OBSERVATION ({ctx}): 405 - the DELETE face is not exposed by this deployment")
        return FACE_UNREACHABLE
    if 400 <= status < 500:
        return True
    script_error(f"unexpected status {status} on {ctx}; no defect conclusion (raw={str(raw)[:200]})")


def live_peer_ids():
    """Derive the live peer inventory from GET /cluster (cluster+status; documented
    'valid on single-node deployment'). Any battery id found here is excluded - only
    non-live ids belong in the invalid-peer battery."""
    try:
        s, raw = safe_request("GET", "cluster_status")
        print(f"[GET /cluster] status={s} raw={str(raw)[:300]}")
        if s != 200:
            return set()
        res = result_node(raw) or {}
        ids = set()
        peers = res.get("peers")
        if isinstance(peers, dict):
            for k in peers.keys():
                if str(k).lstrip("-").isdigit():
                    ids.add(int(k))
        elif isinstance(peers, list):
            for p in peers:
                if isinstance(p, dict) and isinstance(p.get("peer_id"), int):
                    ids.add(p["peer_id"])
        if ids:
            print(f"[GET /cluster] live peers discovered: {sorted(ids)} - excluded from the ghost battery")
        else:
            print("[GET /cluster] no live peer inventory exposed (disabled mode) - all battery ids are non-live")
        return ids
    except Exception as e:
        print(f"[GET /cluster] discovery failed ({e}) - treated as no inventory; battery unchanged")
        return set()


def main():
    hs, _ = safe_request("GET", "healthz")
    if hs != 200:
        script_error(f"/healthz pre-probe returned {hs}; deployment not reachable")
    print(f"[pre-probe] /healthz status={hs}")

    live = live_peer_ids()
    battery = [
        (0, "peer_id=0 (never a generated peer id)"),
        (1, "peer_id=1 (lowest plausible id, not in inventory)"),
        (987654321987654321, "peer_id=987654321987654321 (random-large ghost)"),
        (18446744073709551615, "peer_id=u64-max ghost"),
    ]
    skipped = [pid for pid, _ in battery if pid in live]
    if skipped:
        print(f"OBSERVATION: battery ids {skipped} are live peers on this deployment - skipped (removing one would be the destructive last-peer face, attacked in semantic_cluster_peer_delete_005)")

    refused = 0
    unreachable = 0
    for pid, desc in battery:
        if pid in live:
            continue
        st, raw = safe_request("DELETE", REMOVE_PEER_KEY, path_params={"peer_id": pid}, timeout=15)
        outcome = classify_probe(st, raw, desc)
        if outcome is FACE_UNREACHABLE:
            unreachable += 1
        else:
            refused += 1

    print("OBSERVATION (positive face): no valid removable peer exists on this deployment "
          "(single node, cluster status disabled) - every live peer would simultaneously be "
          "the destructive 'last peer' case, which is the state constraint's guarded face "
          "(semantic_cluster_peer_delete_005); the 200-on-valid face is therefore not judged here")

    if refused == 0 and unreachable > 0:
        script_error("every probe answered 405 - the DELETE peer-removal face is not exposed "
                     "by this deployment; the documented disposition cannot be adjudicated")
    print(f"[summary] {refused} clean 4xx refusals on invalid peer ids, 0 illegal successes")
    print("VERDICT: NO_DEFECT")


if __name__ == "__main__":
    main()
