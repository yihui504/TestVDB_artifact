#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_cluster_telemetry_001
# strategy: count_consistency
# endpoint: cluster+telemetry
# constraint_ids: qdrant_behavioral_cluster_telemetry_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/distributed/cluster-telemetry
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 (state-transition consistency matrix) on the ops face
  GET /cluster/telemetry (cluster+telemetry; URL read verbatim from
  raw_knowledge api_endpoints[].url and registered into rt.PATHS so
  rt.request stays the single HTTP exit), with Strategy 2's post-DELETE
  phase folded as the final matrix phase. The behavioral assertion promises
  HTTP 200 with a telemetry payload on this global ops face (no
  per-collection dependency), and the contract grid materializes
  result.cluster.{enabled, number_of_peers, peers} + result.collections.
  R8 lesson applied: shape checks on grid sections are graded only when the
  section materializes (a flat-grid that exists in no published OpenAPI must
  not become a false oracle); the hard core is 200 + parseable JSON +
  result-object envelope. Sequence (both faces probed per phase: default
  no-param face and the documented details_level=10 closure face):
  (P0) control probes + fingerprints -> (P1) create collection C ->
  visibility leg: C must surface in the details-10 collections name view
  (converging poll; blindness to a live collection while other names show =
  Type4) -> (P2) upsert 8 wait=true + exact count control 8 -> (P3) payload
  index create -> (P4) delete 4 wait=true + exact count control 4 ->
  (P5) drop + quiescence control (describe = 404) -> post-delete legs:
  default face must still be 200 with the SAME fingerprint, and C's name
  must leave the details-10 collections view (a quiesced drop still
  reported = stale telemetry state = Type4). Per-phase: a data-plane
  mutation flipping the telemetry state view (result key set / cluster
  enabled / number_of_peers) = Type4; 5xx = Type3 only after /healthz
  liveness; transport failure = inline /healthz probe. Sequential matrix ->
  single occurrence is decisive (the >=2 damping is for race-window
  scripts 002/003).
  [chunk_cluster+telemetry coverage: count_consistency (state-transition
  matrix + post-delete collections-view invisibility) x
  qdrant_behavioral_cluster_telemetry_001 (200-across-mutations clause +
  telemetry-state-tracks-create/drop clause)]
Oracle: every default-face probe at every phase returns 200 with result a
  JSON object whose fingerprint (result key set, cluster.enabled,
  cluster.number_of_peers) equals the P0 baseline (drift =
  Type4_StateLogicViolation); details_level=10 (documented 0..10 closure)
  returns 200 with the same envelope guarantee; when the cluster section
  materializes, enabled is boolean, number_of_peers is integer|null and
  peers is a map (violation = Type4); after create, C surfaces in the
  details-10 collections name view while other names are visible
  (never-surfacing = Type4); count controls 8 then 4 must hold (drift =
  Type4); after the verified drop (describe = 404) and a 10s convergence
  window, C's name is absent from the details-10 collections view (still
  present = Type4); any 5xx = Type3_RuntimeFailure only after /healthz 200
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

# documented TelemetryData sections (doc_quote) — logged as OBSERVATION only,
# never judged (R8 lesson: doc section lists may not match the live shape)
DOC_SECTIONS = ("id", "app", "collections", "cluster", "requests", "memory",
                "hardware", "search_pool", "quota")


def load_telemetry_template():
    """Standing lesson: derive the URL only from raw_knowledge
    api_endpoints[].url (entry with path == "cluster+telemetry"). No literal
    path invented."""
    for _p in Path(__file__).resolve().parents:
        _rk = _p / "raw_knowledge.json"
        if _rk.exists():
            try:
                for _e in json.loads(_rk.read_text(encoding="utf-8")).get("api_endpoints", []):
                    if _e.get("path") == "cluster+telemetry" and _e.get("url"):
                        return _e["url"]
            except Exception:
                return None
    return None


_TLM_TPL = load_telemetry_template()
if not _TLM_TPL:
    print("VERDICT: SCRIPT_ERROR - cluster+telemetry url not derivable from raw_knowledge api_endpoints[].url")
    sys.exit(2)
# register derived template so the path_key lives inside rt.PATHS (whitelist
# honored; rt.request stays the single HTTP exit with runtime auth/base handling)
rt.PATHS["cluster_telemetry"] = _TLM_TPL
print(f"[url-derived] cluster+telemetry -> {_TLM_TPL} (raw_knowledge api_endpoints[].url)")


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; forwards timeout/path_params/body/
    query_params exactly (R7 standing lesson). Inline liveness probes
    (GET healthz) stay in this exact call form for static-check visibility."""
    return rt.request(method, path_key, body=body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def alive():
    """Liveness re-check via the lightweight documented health endpoint."""
    hs, hraw = safe_request("GET", "healthz")
    print(f"[healthz] status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_body(raw):
    """Return (top_dict, None) on a parseable object body else (None, detail)."""
    try:
        b = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return None, f"unparseable body ({e})"
    if not isinstance(b, dict):
        return None, "top-level body not an object"
    return b, None


def parse_view(raw):
    """result.<field> envelope (standing lesson): (result_dict, None) | (None, err)."""
    b, err = parse_body(raw)
    if b is None:
        return None, err
    node = b.get("result")
    if not isinstance(node, dict):
        return None, "result envelope not an object"
    return node, None


def envelope_type_defects(b, where):
    """Top-level envelope grid rows (time: number, status: string) — universal
    qdrant envelope, judged when present."""
    out = []
    if "time" in b:
        t = b.get("time")
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            out.append(f"({where}) top-level time not a number: {t!r}")
    if "status" in b and not isinstance(b.get("status"), str):
        out.append(f"({where}) top-level status not a string: {b.get('status')!r}")
    return out


def fingerprint(node):
    """State-view fingerprint at one details face: (result key set,
    cluster.enabled, cluster.number_of_peers)."""
    keys = frozenset(node.keys()) if isinstance(node, dict) else None
    cl = node.get("cluster") if isinstance(node, dict) else None
    enabled = cl.get("enabled") if isinstance(cl, dict) else None
    npeers = cl.get("number_of_peers") if isinstance(cl, dict) else None
    return (keys, enabled, npeers)


def cluster_type_defects(node, where):
    """Grid-typed checks on result.cluster — graded ONLY when the section
    materializes (R8 lesson: absence of a grid section is an OBSERVATION)."""
    out = []
    cl = node.get("cluster") if isinstance(node, dict) else None
    if cl is None:
        return out
    if not isinstance(cl, dict):
        out.append(f"({where}) result.cluster present but not an object: "
                   f"{type(cl).__name__}")
        return out
    if "enabled" in cl and not isinstance(cl.get("enabled"), bool):
        out.append(f"({where}) result.cluster.enabled not boolean: {cl.get('enabled')!r}")
    np = cl.get("number_of_peers")
    if "number_of_peers" in cl and not (np is None or
                                        (isinstance(np, int) and not isinstance(np, bool))):
        out.append(f"({where}) result.cluster.number_of_peers not integer|null: {np!r}")
    if "peers" in cl and not isinstance(cl.get("peers"), dict):
        out.append(f"({where}) result.cluster.peers not an object/map: "
                   f"{type(cl.get('peers')).__name__}")
    return out


def names_view(node):
    """Shape-tolerant extraction of candidate collection names from the
    result.collections subtree (pure-string lists, dict 'name' values, and
    string keys of a name->detail map). Exact-match on the unique-prefixed
    collection name downstream, so over-collection is harmless."""
    names = set()

    def walk(x, depth):
        if depth > 6:
            return
        if isinstance(x, list):
            strs = [i for i in x if isinstance(i, str)]
            if strs and len(strs) == len(x):
                names.update(strs)
            else:
                for i in x:
                    walk(i, depth + 1)
        elif isinstance(x, dict):
            for k, v in x.items():
                if isinstance(k, str) and isinstance(v, (dict, list)):
                    names.add(k)
                if k == "name" and isinstance(v, str):
                    names.add(v)
                walk(v, depth + 1)

    coll = node.get("collections") if isinstance(node, dict) else None
    walk(coll if coll is not None else {}, 0)
    return names


def exact_count(name):
    """Control read: exact point count or None on transport/parse failure."""
    s, raw = safe_request("POST", "count", body={"exact": True},
                          path_params={"name": name})
    if s != 200:
        return None
    node, err = parse_view(raw)
    if node is None or not isinstance(node.get("count"), int):
        return None
    return node["count"]


def probe(where, face, base_fp, defects):
    """One telemetry-face probe (face: 'default' | 'd10').
    Returns False only on fatal (dead service)."""
    qp = {"details_level": "10"} if face == "d10" else None
    s, raw = safe_request("GET", "cluster_telemetry", query_params=qp)
    print(f"[{where} {face}] status={s} raw={raw[:300]}")
    if s == 0:
        hs, hraw = safe_request("GET", "healthz")
        print(f"[{where} {face} transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
        if hs != 200:
            return False
        print(f"ENV_ISSUE: transport failure at {where} {face}; liveness re-checked via /healthz")
        return True
    if 500 <= s <= 599:
        if alive():
            defects.append(
                f"({where} {face}) GET cluster telemetry returned {s} (200 "
                f"promised by behavioral assertion, service alive per "
                f"/healthz) — Type3_RuntimeFailure — raw={raw[:200]}"
            )
            return True
        return False
    if s != 200:
        print(f"OBSERVATION ({where} {face}): returned {s} — unexpected "
              f"disposition, not in promise set; recorded, not judged")
        return True
    b, berr = parse_body(raw)
    if b is not None:
        for d in envelope_type_defects(b, where):
            defects.append(d + " — Type4_StateLogicViolation")
        present = [k for k in DOC_SECTIONS if k in b.get("result", {})] \
            if isinstance(b.get("result"), dict) else []
        print(f"[{where} {face}] documented sections materialized: {present}")
    node, err = parse_view(raw)
    if node is None:
        defects.append(
            f"({where} {face}) 200 but {err} — promised telemetry result "
            f"object — Type4_StateLogicViolation — raw={raw[:200]}"
        )
        return True
    for d in cluster_type_defects(node, where):
        defects.append(d + " — Type4_StateLogicViolation")
    if base_fp is not None and fingerprint(node) != base_fp:
        fp_now = fingerprint(node)
        defects.append(
            f"({where} {face}) telemetry state-view fingerprint changed "
            f"across a data-plane transition (baseline "
            f"keys={sorted(base_fp[0]) if base_fp[0] else None} "
            f"enabled={base_fp[1]!r} npeers={base_fp[2]!r} -> "
            f"keys={sorted(fp_now[0]) if fp_now[0] else None} "
            f"enabled={fp_now[1]!r} npeers={fp_now[2]!r}) — no deployment "
            f"change occurred — Type4_StateLogicViolation"
        )
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sctlm1_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    try:
        # ---- P0: control probes on both faces (baseline fingerprints) ----
        s, raw = safe_request("GET", "cluster_telemetry")
        print(f"[P0 control probe: documented no-param GET] status={s} raw={raw[:300]}")
        if s == 0:
            hs, hraw = safe_request("GET", "healthz")
            print(f"[P0 transport] /healthz probe status={hs} raw={str(hraw)[:120]}")
            return "SCRIPT_ERROR"
        if s != 200:
            print(f"SETUP_ERROR: baseline cluster telemetry = {s}")
            return "SCRIPT_ERROR"
        node, err = parse_view(raw)
        if node is None:
            DEFECTS.append(
                f"(P0 default) baseline 200 but {err} — promised telemetry "
                f"result object — Type4_StateLogicViolation — raw={raw[:200]}"
            )
            base_fp = None
        else:
            base_fp = fingerprint(node)
            print(f"[P0 default fingerprint] keys={sorted(base_fp[0])} "
                  f"enabled={base_fp[1]!r} npeers={base_fp[2]!r}")
            for d in cluster_type_defects(node, "P0 default"):
                DEFECTS.append(d + " — Type4_StateLogicViolation")
        b0, _ = parse_body(raw)
        if b0 is not None:
            for d in envelope_type_defects(b0, "P0 default"):
                DEFECTS.append(d + " — Type4_StateLogicViolation")

        d10_ok = True
        s, raw = safe_request("GET", "cluster_telemetry",
                              query_params={"details_level": "10"})
        print(f"[P0 details_level=10 probe] status={s} raw={raw[:300]}")
        if s != 200:
            print(f"OBSERVATION (P0 d10): details_level=10 returned {s} — "
                  f"visibility legs degrade to OBSERVATION; default-face "
                  f"matrix still judged")
            d10_ok = False
            base_fp_d10 = None
        else:
            node_d10, err_d10 = parse_view(raw)
            if node_d10 is None:
                DEFECTS.append(
                    f"(P0 d10) 200 but {err_d10} — Type4_StateLogicViolation "
                    f"— raw={raw[:200]}"
                )
                base_fp_d10 = None
            else:
                base_fp_d10 = fingerprint(node_d10)
                for d in cluster_type_defects(node_d10, "P0 d10"):
                    DEFECTS.append(d + " — Type4_StateLogicViolation")

        # ---- P1: create collection C + details-10 visibility leg ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR create {C}: {err}")
            return "SCRIPT_ERROR"
        if not probe("P1 after create", "default", base_fp, DEFECTS):
            return "SCRIPT_ERROR"
        seen_c = False
        saw_other_names = False
        if d10_ok:
            for _ in range(12):
                s2, raw2 = safe_request("GET", "cluster_telemetry",
                                        query_params={"details_level": "10"})
                if s2 == 200:
                    node2, _e2 = parse_view(raw2)
                    if node2 is not None:
                        names = names_view(node2)
                        if C in names:
                            seen_c = True
                            break
                        if names:
                            saw_other_names = True
                time.sleep(0.5)
            print(f"[P1 visibility] C in details-10 collections view? {seen_c} "
                  f"(other names visible: {saw_other_names})")
            if not seen_c and saw_other_names:
                DEFECTS.append(
                    f"(P1 visibility) live collection {C} never surfaced in "
                    f"the details-10 collections view across a 6s converging "
                    f"poll while other collection names were visible — "
                    f"telemetry state blind to a live collection — "
                    f"Type4_StateLogicViolation"
                )
            elif not seen_c:
                print("OBSERVATION (P1): per-collection names do not "
                      "materialize in this telemetry shape — visibility leg "
                      "unjudgeable (R8 lesson), recorded")
            if not probe("P1 after create", "d10", base_fp_d10, DEFECTS):
                return "SCRIPT_ERROR"

        # ---- P2: upsert 8 points (wait=true) + count control = 8 ----
        pts = [{"id": i, "vector": [0.1 * (i + 1), 0.2, 0.3, 0.4],
               "payload": {"city": "tokyo"}} for i in range(8)]
        s, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[P2 seed upsert wait=true] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR: seed upsert = {s}")
            return "SCRIPT_ERROR"
        cnt = exact_count(C)
        print(f"[P2 count control] exact={cnt} expected=8")
        if cnt is not None and cnt != 8:
            DEFECTS.append(
                f"(P2) count control drift after wait=true upsert: expected "
                f"8, got {cnt} — Type4_StateLogicViolation"
            )
        if not probe("P2 after upsert", "default", base_fp, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- P3: create payload index (config-plane mutation) ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": "city", "field_schema": "keyword"},
                              path_params={"name": C})
        print(f"[P3 create index] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"ENV_ISSUE: index create = {s} (phase mutation not landed; "
                  f"following probe still valid)")
        if not probe("P3 after index create", "default", base_fp, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- P4: delete 4 points (wait=true) + count control = 4 ----
        s, raw = safe_request("POST", "delete_points", body={"points": [0, 1, 2, 3]},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[P4 delete wait=true] status={s} raw={raw[:200]}")
        if s not in (200, 201):
            print(f"SETUP_ERROR: delete = {s}")
            return "SCRIPT_ERROR"
        cnt = exact_count(C)
        print(f"[P4 count control] exact={cnt} expected=4")
        if cnt is not None and cnt != 4:
            DEFECTS.append(
                f"(P4) count control drift after wait=true delete: expected "
                f"4, got {cnt} — Type4_StateLogicViolation"
            )
        if not probe("P4 after delete", "default", base_fp, DEFECTS):
            return "SCRIPT_ERROR"

        # ---- P5: drop + quiescence + post-delete legs (strategy 2) ----
        ds, draw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[P5 drop] status={ds} raw={draw[:200]}")
        if ds not in (200, 404):
            print(f"SETUP_ERROR: drop returned {ds}")
            return "SCRIPT_ERROR"
        gone = False
        for _ in range(20):
            try:
                cs, craw = safe_request("GET", "describe_collection",
                                        path_params={"name": C})
            except Exception:
                cs = -1
            if cs == 404:
                gone = True
                break
            time.sleep(0.5)
        print(f"[P5 quiescence] describe({C}) -> 404? {gone}")
        if not gone:
            print("ENV_ISSUE: drop not observable via describe within retries "
                  "— post-delete legs judged on best effort")
        if not probe("P5 post-delete", "default", base_fp, DEFECTS):
            return "SCRIPT_ERROR"
        # post-delete invisibility in the details-10 collections view
        if d10_ok and seen_c:
            still_there = True
            for attempt in range(20):
                s2, raw2 = safe_request("GET", "cluster_telemetry",
                                        query_params={"details_level": "10"})
                if s2 == 200:
                    node2, _e2 = parse_view(raw2)
                    if node2 is not None and C not in names_view(node2):
                        still_there = False
                        print(f"[P5 post-delete] C left the collections view "
                              f"after {attempt} poll(s)")
                        break
                time.sleep(0.5)
            if still_there:
                DEFECTS.append(
                    f"(P5 post-delete) quiesced drop (describe = 404) still "
                    f"reported by the details-10 collections view after a 10s "
                    f"convergence window — stale telemetry state — "
                    f"Type4_StateLogicViolation"
                )
        elif d10_ok:
            print("OBSERVATION (P5): visibility leg was never established "
                  "(names did not materialize) — post-delete invisibility leg "
                  "unjudgeable, recorded")
        # final type-side re-check on the default face
        s, raw = safe_request("GET", "cluster_telemetry")
        print(f"[P5 final type-check] status={s} raw={raw[:300]}")
        if s == 200:
            node, perr = parse_view(raw)
            if node is not None:
                for d in cluster_type_defects(node, "P5 final"):
                    DEFECTS.append(d + " — Type4_StateLogicViolation")
            b5, _ = parse_body(raw)
            if b5 is not None:
                for d in envelope_type_defects(b5, "P5 final"):
                    DEFECTS.append(d + " — Type4_StateLogicViolation")

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
    try:
        _v = main()
    except Exception as _e:  # never exit without the strict VERDICT line
        print(f"FATAL: {_e}")
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
