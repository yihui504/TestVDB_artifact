#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_overwrite_006
# strategy: count_consistency
# endpoint: payload+overwrite
# constraint_ids: qdrant_bc_payload_overwrite_replace_001
# source_url: https://qdrant.tech/documentation/manage-data/points/
# doc_version: 1.18.x (versioned v-1-18-x api-reference); BC source is site-current (no version archive)
"""
Attack: Behavioral-contract scenario replay against
  qdrant_bc_payload_overwrite_replace_001: "payload overwrite replaces
  the whole payload of the targeted points instead of merging";
  scenario: "set payload keys {a,b} -> PUT payload+overwrite with {c}
  (wait=true) -> GET the points with payload"; expected: "after
  overwrite the record payload equals exactly {c}; the previously
  stored keys {a,b} are removed (set semantics, not merge)". The BC's
  related_endpoints trio (payload+set, payload+overwrite, points+get)
  is exercised end-to-end with points+get as the readback channel:
  (A setup) 2 points with vectors, payload {"orig":true}.
  (B set {a,b}) POST payload+set {"a":1,"b":"two"} wait=true -> 200;
      points+get readback: BOTH points payload EXACTLY {"a":1,
      "b":"two"} (the scenario's precondition — if set itself fails,
      the script exits SETUP_ERROR, not defect).
  (C overwrite {c}) PUT payload+overwrite {"c":"three"} wait=true ->
      200 (a 4xx/5xx on the BC's own documented flow is adjudicated:
      4xx = the pinned scenario rejected — Type4; 5xx = Type3 when
      /healthz alive).
  (D readback, THE BC assertion) points+get with_payload: BOTH points
      payload EXACTLY {"c":"three"}; keys "a" and "b" ABSENT. Any
      surviving a/b = merge semantics (the exact behavior the BC
      forbids) — Type4_StateLogicViolation.
  (E verb-asymmetry contrast) POST payload+set {"a":1} wait=true ->
      200; readback EXACTLY {"a":1,"c":"three"} — the POST verb MERGES
      into the current payload. This guards the discrimination: if PUT
      had merged, D already fails; if POST replaced, E readback would
      be {"a":1} — either way the replace-vs-merge contract is broken.
  (F vector preservation) both vectors equal the baseline readback
      (<=1e-6; R27 lesson — Cosine normalizes by-design, so the
      comparison is readback-vs-baseline-readback only) and exact
      count stays 2.
  points+get URL registered VERBATIM from raw_knowledge
  api_endpoints[].url ("/collections/{collection_name}/points",
  POST). Its contract response_shape pins result: array with
  result[].payload / result[].vector — the readback oracle accesses
  exactly those paths.
  [chunk_payload+overwrite coverage: count_consistency x
   qdrant_bc_payload_overwrite_replace_001 (BC scenario replay:
   set {a,b} -> overwrite {c} -> points+get exact {c} + verb
   asymmetry + vector/count invariance)]
Oracle: after set {"a":1,"b":"two"} (200) both readback payloads are
  EXACTLY {"a":1,"b":"two"}; after PUT overwrite {"c":"three"} (200)
  both are EXACTLY {"c":"three"} with a/b absent; after set {"a":1}
  (200) both are EXACTLY {"a":1,"c":"three"}; vectors equal baseline
  readback (<=1e-6) and exact count stays 2. A surviving a/b after
  the overwrite (merge instead of replace), a 4xx/5xx on the BC's own
  documented flow, a non-merged set readback, a vector change, or a
  count drift = Type4_StateLogicViolation; 5xx only counts when
  /healthz confirms liveness (Type3_RuntimeFailure).
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

# payload+overwrite / payload+set / points+get are not in the runtime PATHS
# whitelist — register VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "payload+overwrite", "method": "PUT",
#    "url": "/collections/{collection_name}/points/payload"}
#   {"path": "payload+set", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload"}
#   {"path": "points+get", "method": "POST",
#    "url": "/collections/{collection_name}/points"}
rt.PATHS["payload_overwrite"] = "/collections/{collection_name}/points/payload"
rt.PATHS["payload_set"] = "/collections/{collection_name}/points/payload"
rt.PATHS["points_get"] = "/collections/{collection_name}/points"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k or k == 'points_get']}")
if (rt.PATHS.get("payload_overwrite") != "/collections/{collection_name}/points/payload"
        or rt.PATHS.get("payload_set") != "/collections/{collection_name}/points/payload"
        or rt.PATHS.get("points_get") != "/collections/{collection_name}/points"):
    print("VERDICT: SCRIPT_ERROR - endpoint URL registration failed")
    sys.exit(2)

DEFECTS = []


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def get_points(tag, coll):
    """POST points+get with ids+with_payload+with_vector ->
    {id: point} per the pinned response_shape (result: array of point
    objects with result[].payload / result[].vector), or None on abort."""
    s, raw = safe_request("POST", "points_get",
                          path_params={"collection_name": coll},
                          body={"ids": [1, 2], "with_payload": True,
                                "with_vector": True})
    print(f"[{tag} points+get] status={s} raw={str(raw)[:180]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) points+get returned {s} with service "
                           f"alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
        return None
    if s != 200:
        print(f"SETUP_ERROR: points+get returned {s}")
        return None
    try:
        res = json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        res = None
    if not isinstance(res, list):
        print(f"SETUP_ERROR: points+get result is not an array — "
              f"raw={str(raw)[:200]}")
        return None
    return {p.get("id"): p for p in res if isinstance(p, dict)}


def pay_dict(p):
    pl = p.get("payload")
    if pl is None:
        return {}, True
    if isinstance(pl, dict):
        return pl, True
    return {}, False


def vec_of(p):
    v = p.get("vector")
    return v if isinstance(v, list) else None


def vec_eq(a, b, tol=1e-6):
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return False
    return all(isinstance(x, (int, float)) and isinstance(y, (int, float))
               and abs(x - y) <= tol for x, y in zip(a, b))


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return None
    if s != 200:
        print(f"SETUP_ERROR: count returned {s}")
        return None
    try:
        cnt = json.loads(raw).get("result", {}).get("count")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        cnt = None
    if isinstance(cnt, bool) or not isinstance(cnt, int):
        print(f"SETUP_ERROR: count result.count missing — raw={str(raw)[:200]}")
        return None
    return cnt


def bc_mutation(tag, method, path_key, payload, coll):
    """wait=true set/overwrite mutation -> (status, raw); 5xx/transport
    adjudicated inline, other non-200 returned to caller."""
    s, raw = safe_request(method, path_key,
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": [1, 2]},
                          query_params={"wait": "true"})
    print(f"[{tag} {method} {payload!r}] status={s} raw={str(raw)[:180]}")
    if s == 0:
        liveness(tag)
        return -2, raw
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]} "
                           f"(qdrant_bc_payload_overwrite_replace_001)")
        return -2, raw
    return s, raw


def readback_expect(tag, coll, expected, basevec):
    """points+get readback; both payloads EXACTLY expected; vectors/count."""
    m = get_points(tag, coll)
    if m is None:
        return None
    if set(m.keys()) != {1, 2}:
        DEFECTS.append(f"({tag}) points+get returned ids {sorted(m.keys())} "
                       f"!= [1, 2] — payload operations must not delete "
                       f"points — Type4_StateLogicViolation")
    for pid in (1, 2):
        if pid not in m:
            continue
        pl, okp = pay_dict(m[pid])
        if not okp:
            DEFECTS.append(f"({tag}) point {pid} payload is not an object — "
                           f"Type4_StateLogicViolation")
        elif pl != expected:
            DEFECTS.append(f"({tag}) point {pid} payload {pl!r} != expected "
                           f"EXACT {expected!r} — "
                           f"qdrant_bc_payload_overwrite_replace_001 pins "
                           f"replace-not-merge — Type4_StateLogicViolation")
        else:
            print(f"[{tag}] OK: point {pid} payload exactly {expected!r}")
        if not vec_eq(vec_of(m[pid]), basevec.get(pid)):
            DEFECTS.append(f"({tag}) point {pid} vector changed: "
                           f"{vec_of(m[pid])!r} != baseline "
                           f"{basevec.get(pid)!r} — payload operations are "
                           f"payload-scoped — Type4_StateLogicViolation")
    cnt = exact_count(tag + " count", coll)
    if cnt is not None and cnt != 2:
        DEFECTS.append(f"({tag}) exact count {cnt} != 2 — "
                       f"Type4_StateLogicViolation")
    return m


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spo6_" + TS + "_"
    C = PFX + "col"

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": [
                                      {"id": 1, "vector": [1.0, 2.0, 3.0, 4.0],
                                       "payload": {"orig": True}},
                                      {"id": 2, "vector": [4.0, 3.0, 2.0, 1.0],
                                       "payload": {"orig": True}}]},
                                  query_params={"wait": "true"})
        print(f"[A upsert] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        m0 = get_points("A baseline", C)
        if m0 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        BASEVEC = {pid: vec_of(m0.get(pid, {})) for pid in (1, 2)}
        if any(v is None for v in BASEVEC.values()):
            print("SETUP_ERROR: baseline readback missing vectors")
            return "SCRIPT_ERROR"

        # ---- (B set {a,b}) scenario precondition ----
        s, _ = bc_mutation("B set {a,b}", "POST", "payload_set",
                           {"a": 1, "b": "two"}, C)
        if s == -2:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            print(f"SETUP_ERROR: BC scenario precondition (set) returned {s}")
            return "SCRIPT_ERROR"
        time.sleep(0.3)
        if readback_expect("B readback", C, {"a": 1, "b": "two"},
                           BASEVEC) is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (C overwrite {c}) THE BC mutation ----
        s, _ = bc_mutation("C overwrite {c}", "PUT", "payload_overwrite",
                           {"c": "three"}, C)
        if s == -2:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            DEFECTS.append(f"(C overwrite) the BC's own documented scenario "
                           f"flow (set {{a,b}} -> PUT overwrite) returned "
                           f"{s}, not 200 — Type4_StateLogicViolation")
        time.sleep(0.3)

        # ---- (D readback: exactly {c}, a/b removed) ----
        md = readback_expect("D readback", C, {"c": "three"}, BASEVEC)
        if md is not None:
            for pid in (1, 2):
                if pid in md:
                    pl, _ = pay_dict(md[pid])
                    for oldk in ("a", "b"):
                        if oldk in pl:
                            print(f"[D] replace-vs-merge discriminator: "
                                  f"point {pid} still carries {oldk!r} — "
                                  f"MERGE semantics observed")
        if md is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (E verb-asymmetry contrast: set merges) ----
        s, _ = bc_mutation("E set {a} merge", "POST", "payload_set",
                           {"a": 1}, C)
        if s == -2:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            DEFECTS.append(f"(E set) valid set after overwrite returned {s}, "
                           f"not 200 — Type4_StateLogicViolation")
        time.sleep(0.3)
        if readback_expect("E readback", C, {"a": 1, "c": "three"},
                           BASEVEC) is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

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
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
