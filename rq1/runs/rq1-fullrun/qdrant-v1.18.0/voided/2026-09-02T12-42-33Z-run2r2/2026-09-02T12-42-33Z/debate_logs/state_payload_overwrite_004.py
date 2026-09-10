#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_overwrite_004
# strategy: count_consistency
# endpoint: payload+overwrite
# constraint_ids: qdrant_state_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 1 variant (filter-targeted full-replacement overwrite)
  against qdrant_state_payload_overwrite_001: "overwrite replaces the
  ENTIRE payload of the targeted points (set semantics: keys missing
  from the new payload are removed)". The endpoint's request schema
  carries TWO targeting branches — explicit `points` (covered by
  state_payload_overwrite_001) and `filter` (same SetPayload family:
  "points OR filter must identify targets"). This script mutates the
  SELECTOR from explicit ids to a payload predicate — the mutation
  point where over/under-replacement risk is highest, because the
  storage layer must resolve the predicate to exactly the matching
  ids AND THEN wipe each matched point's whole payload:
  (A setup) 8 points; payload {"grp":"a"|"b","n":i,"keep":"k"} — ids
      0-3 grp=a, ids 4-7 grp=b; baseline readback snapshots the stored
      vectors (R27 lesson: readback-vs-baseline-readback only — Cosine
      normalizes by-design).
  (D mutation) PUT payload+overwrite body {"payload":{"n":"gone",
      "new":1},"filter":{"must":[{"key":"grp","match":{"value":"a"}}]}}
      wait=true -> 200. Sharpest available set-semantics probe: the
      replacement payload OMITS the very key ("grp") the filter
      matched on — full replacement must remove even the selector
      key from every matched point.
  (E selective readback) matched ids 0-3 -> payload EXACTLY
      {"n":"gone","new":1}: a surviving "grp" or "keep" = merge
      semantics; a missing "new" = dropped write; a stale "n" value =
      partial replace. NON-matched ids 4-7 -> payload the exact
      original 3-key dict (any change = the predicate over-matched).
  (F vector preservation) all 8 vectors equal baseline readback
      (<=1e-6).
  (G count invariance) exact count stays 8 (filter-targeted overwrite
      is not point deletion — a matched-point loss = phantom delete).
  (H convergence follow-up) a second identical overwrite (idempotent
      repeat through the filter branch) must keep ids 0-3 at EXACTLY
      {"n":"gone","new":1} and ids 4-7 untouched.
  Persistence judged via scroll readback — never via the response
  alone. The 200 envelope is printed informational-only (no pinned
  response_shape for payload+overwrite in the contract/OpenAPI).
  [chunk_payload+overwrite coverage: count_consistency x
   qdrant_state_payload_overwrite_001 (filter-selector full
   replacement incl. selector-key removal + non-match integrity +
   idempotent repeat)]
Oracle: after a wait=true filter-targeted overwrite (expect HTTP 200)
  {"payload":{"n":"gone","new":1},"filter":must grp=a} on the 8-point collection: ids 0-3 payload EXACTLY
  {"n":"gone","new":1} (grp and keep removed — even the selector key);
  ids 4-7 payload equals the original {"grp":"b","n":i,"keep":"k"};
  all 8 vectors equal baseline readback (<=1e-6); exact count 8
  before and after, unchanged by an identical repeat. A surviving
  "grp"/"keep" on a matched point, any change on a non-matched point,
  a matched-point loss, a vector change, or a count drift =
  Type4_StateLogicViolation; 5xx only counts when /healthz confirms
  liveness (Type3_RuntimeFailure).
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

# payload+overwrite is not in the runtime PATHS whitelist — register VERBATIM
# from raw_knowledge api_endpoints[].url:
#   {"path": "payload+overwrite", "method": "PUT",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_overwrite"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if rt.PATHS.get("payload_overwrite") != "/collections/{collection_name}/points/payload":
    print("VERDICT: SCRIPT_ERROR - payload_overwrite URL registration failed")
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


def scroll_map(tag, coll, limit=50):
    """scroll with_payload+with_vector -> {id: point} or None on abort."""
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": limit, "with_payload": True,
                                "with_vector": True})
    print(f"[{tag} scroll] status={s} raw={str(raw)[:160]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) scroll returned {s} with service "
                           f"alive — Type3_RuntimeFailure — raw={str(raw)[:150]}")
        return None
    if s != 200:
        print(f"SETUP_ERROR: scroll returned {s}")
        return None
    try:
        res = json.loads(raw).get("result")
        pts = res.get("points") if isinstance(res, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        pts = None
    if not isinstance(pts, list):
        print(f"SETUP_ERROR: scroll result.points missing — raw={str(raw)[:200]}")
        return None
    return {p.get("id"): p for p in pts if isinstance(p, dict)}


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


def adjudicate_readback(tag, m, original, newpay):
    """Matched ids 0-3 == newpay exactly; non-matched 4-7 == original."""
    if set(m.keys()) != set(range(8)):
        DEFECTS.append(f"({tag}) point id set {sorted(m.keys())} != 0..7 — "
                       f"filter-targeted overwrite must not delete points — "
                       f"Type4_StateLogicViolation")
    for i in range(8):
        if i not in m:
            continue
        pl, okp = pay_dict(m[i])
        if not okp:
            DEFECTS.append(f"({tag}) point {i} payload is not an object — "
                           f"Type4_StateLogicViolation")
            continue
        if i <= 3:
            for oldk in ("grp", "keep"):
                if oldk in pl:
                    DEFECTS.append(f"({tag}) MATCHED point {i} still carries "
                                   f"omitted key {oldk!r} (the filter matched "
                                   f"on 'grp' — full replacement must remove "
                                   f"even the selector key) — payload={pl!r} "
                                   f"— Type4_StateLogicViolation")
            if pl != newpay:
                DEFECTS.append(f"({tag}) MATCHED point {i} payload {pl!r} != "
                               f"EXACT replacement {newpay!r} — set "
                               f"semantics — Type4_StateLogicViolation")
            else:
                print(f"[{tag}] OK: matched point {i} payload exactly "
                      f"{newpay!r} (selector key 'grp' removed)")
        else:
            if pl != original[i]:
                DEFECTS.append(f"({tag}) NON-matched point {i} payload "
                               f"changed by grp=a overwrite: {pl!r} != "
                               f"{original[i]!r} — predicate over-match — "
                               f"Type4_StateLogicViolation")
            else:
                print(f"[{tag}] OK: non-matched point {i} payload intact")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spo4_" + TS + "_"
    C = PFX + "col"

    IDS = list(range(8))
    ORIGINAL = {i: {"grp": "a" if i <= 3 else "b", "n": i, "keep": "k"}
                for i in IDS}
    NEWPAY = {"n": "gone", "new": 1}
    FILT = {"must": [{"key": "grp", "match": {"value": "a"}}]}

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i) + 1.0, 1.0, 2.0, 3.0],
                "payload": ORIGINAL[i]} for i in IDS]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 8] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"

        base = scroll_map("A baseline", C)
        if base is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if set(base.keys()) != set(IDS):
            print("SETUP_ERROR: baseline id set != 0..7")
            return "SCRIPT_ERROR"
        BASEVEC = {i: vec_of(base[i]) for i in IDS}
        if any(v is None for v in BASEVEC.values()):
            print("SETUP_ERROR: baseline readback missing vectors")
            return "SCRIPT_ERROR"
        for i in IDS:
            pl, _ = pay_dict(base[i])
            if pl != ORIGINAL[i]:
                DEFECTS.append(f"(A baseline) point {i} payload {pl!r} != "
                               f"uploaded {ORIGINAL[i]!r} — "
                               f"Type4_StateLogicViolation")
        cnt0 = exact_count("B count-before", C)
        if cnt0 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cnt0 != 8:
            DEFECTS.append(f"(B count-before) expected 8, got {cnt0} — "
                           f"Type4_StateLogicViolation")

        # ---- (D mutation) filter-targeted full replacement, wait=true ----
        for attempt in ("D overwrite", "H overwrite repeat"):
            d_s, d_raw = safe_request("PUT", "payload_overwrite",
                                      path_params={"collection_name": C},
                                      body={"payload": NEWPAY, "filter": FILT},
                                      query_params={"wait": "true"})
            print(f"[{attempt} payload={NEWPAY!r} filter=grp:a] status={d_s} "
                  f"raw={d_raw[:200]}")
            if d_s == 0:
                liveness(attempt)
                return "SCRIPT_ERROR"
            if 500 <= d_s <= 599:
                if liveness(attempt):
                    DEFECTS.append(f"({attempt}) returned {d_s} with service "
                                   f"alive — Type3_RuntimeFailure — "
                                   f"raw={d_raw[:150]} "
                                   f"(qdrant_state_payload_overwrite_001)")
                return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
            if d_s != 200:
                print(f"SETUP_ERROR: {attempt} returned {d_s} — cannot judge "
                      f"filter-branch state semantics")
                return "SCRIPT_ERROR"
            time.sleep(0.4)

            # ---- (E selective readback) + (F vectors) ----
            after = scroll_map(f"{attempt} readback", C)
            if after is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            adjudicate_readback(attempt, after, ORIGINAL, NEWPAY)
            for i in IDS:
                if i in after and not vec_eq(vec_of(after[i]), BASEVEC[i]):
                    DEFECTS.append(f"({attempt}) point {i} vector changed: "
                                   f"{vec_of(after[i])!r} != baseline "
                                   f"{BASEVEC[i]!r} — payload overwrite is "
                                   f"payload-scoped — "
                                   f"Type4_StateLogicViolation")

        # ---- (G count invariance after both passes) ----
        cnt1 = exact_count("G count-after", C)
        if cnt1 is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cnt1 != cnt0:
            DEFECTS.append(f"(G) exact count changed after filter-targeted "
                           f"overwrite: {cnt1} != {cnt0} — matched points "
                           f"must survive (phantom delete) — "
                           f"Type4_StateLogicViolation")

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
