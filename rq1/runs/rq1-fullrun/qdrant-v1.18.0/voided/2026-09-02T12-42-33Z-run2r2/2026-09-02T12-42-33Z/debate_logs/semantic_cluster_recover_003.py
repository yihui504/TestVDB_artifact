#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_cluster_recover_003
# strategy: metamorphic
# endpoint: cluster+recover
# constraint_ids: qdrant_behavioral_cluster_recover_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/recover-current-peer
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-01 (Parameter Type Coercion Trust - undocumented body/query inputs
#   silently flipping a disabled face's disposition) + BS-03 (nondeterministic
#   guard state across identical repeats)
"""
Attack: metamorphic (Strategy 6, repeat + variant consistency) x
  assertions::qdrant_behavioral_cluster_recover_001 (chunk_cluster+recover; POST
  /cluster/recover, URL from raw_knowledge api_endpoints[cluster+recover].url).
  The assertion documents a single stable outcome ("returns 200 ok") and the
  endpoint declares NO request parameters besides the api-key header (raw_knowledge
  parameters list) - so the metamorphic relation is disposition invariance: the
  status CLASS of POST /cluster/recover must be identical across (a) identical
  repeats (L1..L3, no body) and (b) undocumented-input variants that a dispatcher
  might mis-route: V1 empty JSON body {}, V2 bogus body {"peer_id": 12345}, V3
  undocumented query param timeout=5. On this standalone deployment the baseline
  class is expected 4xx (R6 lesson: distributed faces refuse); the relation is
  symmetric - if the baseline class is 2xx the repeats must stay 2xx - so no
  premise-void exit is needed. Any leg flipping a disabled-face refusal into 2xx
  (identical repeat or via an undocumented input) means the guard executed a
  destructive reset behind a face it refuses (Type1_IllegalSuccess); any 5xx with
  /healthz alive is Type3. G9: the same input family must get one disposition.
  [chunk_cluster+recover coverage: metamorphic x
   qdrant_behavioral_cluster_recover_001 (repeat invariance + undocumented-input
   invariance of the refusal class)]
Oracle: all six legs (L1 baseline, L2/L3 identical repeats, V1 {}-body, V2
  bogus-body, V3 timeout-query) return the SAME status class as L1 with the same
  refusal description (volatile time excluded); class flip 4xx->2xx (repeat or
  variant) = DEFECT Type1_IllegalSuccess (disabled destructive face executed);
  2xx->non-2xx flip = Type4_StateLogicViolation (nondeterministic guard);
  any 5xx with /healthz alive = Type3_RuntimeFailure; after the battery
  /healthz=200 and the witness collection exact count==2 - drift = Type4

Rationale (G6): repeat + undocumented-input are the two mutations that break
disposition invariance with the least state change - a dispatcher that routes on
body shape (V1/V2) or blindly accepts known query params (V3) executes a
membership-reset the refusal face claims is impossible; identical repeats (L2/L3)
expose guard nondeterminism without any input difference to blame.
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
COL = f"scrc3_{TS}_col"
POINTS = [
    {"id": 11, "vector": [0.2, 0.4, 0.6, 0.8], "payload": {"tag": "alpha"}},
    {"id": 12, "vector": [1.2, 1.4, 1.6, 1.8], "payload": {"tag": "beta"}},
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


def status_class(st):
    if 200 <= st < 300:
        return "2xx"
    if 400 <= st < 500:
        return "4xx"
    if 500 <= st < 599:
        return "5xx"
    return f"other({st})"


def refusal_desc(raw):
    b = jload(raw)
    d = b.get("description") if isinstance(b, dict) else None
    return str(d) if d is not None else ""


def face_guard():
    """R6 lesson: probe the deployment face first; judge only the falsifiable
    status class; exit honestly otherwise."""
    st, raw = safe_request("GET", "cluster_status", timeout=15)
    print(f"[face probe GET /cluster] status={st} raw={str(raw)[:300]}")
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


def recover_leg(tag, body=None, query_params=None):
    """One POST /cluster/recover leg. Returns (status, class, description)."""
    st, raw = safe_request("POST", RECOVER_KEY, body=body,
                           query_params=query_params, timeout=20)
    print(f"[leg {tag}] status={st} class={status_class(st)} raw={str(raw)[:300]}")
    if st == 0:
        liveness("transport")
        script_error(f"transport failure on leg {tag}; no defect conclusion")
    if 500 <= st <= 599:
        hs = liveness(f"5xx-{tag}")
        if hs != 200:
            script_error(f"5xx on leg {tag} and /healthz not 200 (={hs}); no defect conclusion")
        defect("Type3_RuntimeFailure",
               f"leg {tag} of POST /cluster/recover raised {st} while /healthz is alive - a "
               f"disposition probe must never crash the server (assertion "
               f"qdrant_behavioral_cluster_recover_001 documents 200, never 5xx); "
               f"raw={str(raw)[:200]}")
    return st, status_class(st), refusal_desc(raw)


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
        # ---- witness: proves the battery left the data plane untouched ----
        ok, err = rt.setup_default(COL, dim=4, metric="Cosine")
        if not ok:
            script_error(f"setup failed creating {COL}: {err}")
        st, raw = safe_request("PUT", "upsert_points", body={"points": POINTS},
                               path_params={"name": COL},
                               query_params={"wait": "true"}, timeout=20)
        print(f"[witness upsert] status={st} raw={str(raw)[:200]}")
        if st not in (200, 201):
            script_error(f"witness upsert failed ({st}); no defect conclusion")

        # ---- L1 baseline class (relation is symmetric: 4xx or 2xx both fine) ----
        st1, cls1, desc1 = recover_leg("L1 baseline (no body)")
        base_cls, base_desc = cls1, desc1

        # ---- L2/L3 identical repeats ----
        for tag in ("L2 repeat", "L3 repeat"):
            st, cls, desc = recover_leg(tag)
            if cls != base_cls:
                if base_cls == "4xx" and cls == "2xx":
                    defect("Type1_IllegalSuccess",
                           f"identical repeat {tag} flipped the disabled-face refusal into {st} "
                           f"success (baseline {base_cls}) - the guard executed a destructive "
                           f"membership reset nondeterministically behind a face it refuses "
                           f"(assertion qdrant_behavioral_cluster_recover_001 / G9)")
                if base_cls == "2xx":
                    defect("Type4_StateLogicViolation",
                           f"identical repeat {tag} flipped the documented 2xx disposition into "
                           f"{cls} (baseline 2xx) - nondeterministic disposition for byte-identical "
                           f"requests with no state change in between")
                defect("Type4_StateLogicViolation",
                       f"identical repeat {tag} changed disposition class {base_cls} -> {cls} "
                       f"without any input difference")

        # ---- undocumented-input variants (must keep the baseline class) ----
        variants = [
            ("V1 empty body {}", {"body": {}}),
            ("V2 bogus body", {"body": {"peer_id": 12345}}),
            ("V3 undocumented timeout query", {"query_params": {"timeout": "5"}}),
        ]
        for tag, kw in variants:
            st, cls, desc = recover_leg(tag, body=kw.get("body"),
                                        query_params=kw.get("query_params"))
            if cls != base_cls:
                if base_cls == "4xx" and cls == "2xx":
                    defect("Type1_IllegalSuccess",
                           f"variant {tag} flipped the disabled-face refusal into {st} success - "
                           f"an undocumented input armed the destructive recovery the refusal "
                           f"face claims is impossible (BS-01 guard bypass; assertion "
                           f"qdrant_behavioral_cluster_recover_001 / G9)")
                if base_cls == "2xx" and cls != "2xx":
                    defect("Type4_StateLogicViolation",
                           f"variant {tag} flipped the documented 2xx disposition into {cls} - "
                           f"same input family, inconsistent disposition (G9)")
                defect("Type4_StateLogicViolation",
                       f"variant {tag} changed disposition class {base_cls} -> {cls}")
            if base_cls == "4xx" and desc != base_desc:
                print(f"OBSERVATION ({tag}): refusal description differs from baseline "
                      f"(base={base_desc[:100]!r} now={desc[:100]!r}) - same class, recorded for G9")

        # ---- battery reconciliation ----
        hs = liveness("reconcile")
        if hs != 200:
            defect("Type3_RuntimeFailure",
                   f"/healthz returned {hs} after the recover disposition battery - refused "
                   f"probes must not take the deployment down")
        cst, craw = safe_request("POST", "count", body={"exact": True},
                                 path_params={"name": COL}, timeout=15)
        print(f"[reconcile count] status={cst} raw={str(craw)[:200]}")
        cnt = None
        if cst == 200:
            res = jload(craw).get("result")
            cnt = res.get("count") if isinstance(res, dict) else None
        if cst != 200 or cnt != 2:
            defect("Type4_StateLogicViolation",
                   f"witness data plane drifted across the refused/executed recover battery "
                   f"(count={cnt}, expected 2, status {cst}) - disposition probes must be "
                   f"data-plane transparent")
        print(f"[summary] all six legs kept the {base_cls} disposition; data plane intact")
        print("VERDICT: NO_DEFECT")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
