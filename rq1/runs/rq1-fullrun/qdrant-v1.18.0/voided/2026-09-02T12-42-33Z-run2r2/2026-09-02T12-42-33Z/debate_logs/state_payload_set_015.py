#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_set_015
# strategy: delete_consistency
# endpoint: payload+set
# constraint_ids: qdrant_behavioral_payload_set_001, qdrant_state_payload_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (status-face mapping + post-rejection state
  consistency) against qdrant_behavioral_payload_set_001 ("returns 200
  ok on success; 400 when neither points nor filter identifies targets
  or on invalid input; 404 for a missing collection") and
  qdrant_state_payload_set_001 ("both null is rejected"). Every
  rejection face is paired with a STATE readback: a rejected set must
  leave zero partial application (positive-negative pairing per G4).
  (A setup) 3 points ids 1-3, payload {"a":1}; baseline scroll
      snapshots BASEVEC (R27 lesson: readback-vs-baseline-readback
      only for vectors).
  (V1 positive face) set {"ok":1} on points [1] wait=true -> HTTP 200
      pinned ("returns 200 ok on success"); state: point 1 exactly
      {"a":1,"ok":1}, points 2-3 untouched.
  (V2a both-null, omitted form) {"payload":{"x":1}} with NEITHER
      points NOR filter -> must be REJECTED (4xx). A 2xx here = both
      targets absent yet the write succeeded = Type1_IllegalSuccess
      (the exact face qdrant_state_payload_set_001 pins). Exact 4xx
      code is printed; 400-vs-other-4xx NAMING is measured-only (R29
      standing lesson: Type2 error-naming has no anchor).
  (V2b both-null, explicit null form) {"payload":{"x":1},
      "points":null,"filter":null} -> same rejection face.
  (V3 missing collection face) same valid body against a NEVER-created
      collection name -> 404 pinned. 404 = promise kept; a different
      4xx = naming deviation printed, NOT adjudicated (R29); a 2xx =
      success against a nonexistent collection = Type1_IllegalSuccess.
  (V4 invalid-input face) {"payload":[1,2],"points":[1]} — payload is
      pinned type object, an array is invalid input -> 4xx rejection
      pinned; state: point 1 must still be exactly {"a":1,"ok":1}.
  (V5 both-present, measured-only) points AND filter together: which
      selector wins is NOT pinned by the chunk's assertions — status +
      readback printed, NOT adjudicated (G3).
  (F final state sweep) no point anywhere carries the rejected key
      "x"; point 1 exactly {"a":1,"ok":1}; points 2-3 exactly {"a":1};
      id set 1..6-style {1,2,3}; vectors equal BASEVEC; exact count 3.
  [chunk_payload+set coverage: delete_consistency x
   qdrant_behavioral_payload_set_001 + qdrant_state_payload_set_001
   (200/400/404 status faces + post-rejection zero-partial-state)]
Oracle: V1 -> 200 and point 1 = {"a":1,"ok":1}; V2a/V2b -> 4xx (2xx =
  Type1_IllegalSuccess) and afterwards NO point carries "x"; V3 -> 404
  (2xx = Type1_IllegalSuccess against a nonexistent collection; other
  4xx printed, naming not adjudicated); V4 -> 4xx (2xx =
  Type1_IllegalSuccess on invalid payload type) and point 1 unchanged;
  V5 measured-only; final sweep: exact per-point payloads above, id
  set {1,2,3}, vectors equal baseline readback (<=1e-6), count 3; 5xx
  faces count only when /healthz confirms liveness
  (Type3_RuntimeFailure).
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

# payload+set is not in the runtime PATHS whitelist — register VERBATIM
# from raw_knowledge api_endpoints[].url:
#   {"path": "payload+set", "method": "POST",
#    "url": "/collections/{collection_name}/points/payload"}
rt.PATHS["payload_set"] = "/collections/{collection_name}/points/payload"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'payload' in k]}")
if rt.PATHS.get("payload_set") != "/collections/{collection_name}/points/payload":
    print("VERDICT: SCRIPT_ERROR - payload_set URL registration failed")
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


def scroll_map(tag, coll, limit=10):
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


def face(tag, status, raw, reject=True):
    """Shared status-face adjudication.

    reject=True -> the pinned expectation is a 4xx rejection:
      2xx = Type1_IllegalSuccess; 4xx = promise kept (exact code
      printed; 400-vs-other naming measured-only per R29).
    reject=False -> the pinned expectation is 200:
      200 = promise kept; 4xx = SETUP_ERROR (plainly valid op).
    Returns 'ok' | 'defect' | 'abort' | 'setup'.
    """
    print(f"[{tag}] status={status} raw={str(raw)[:200]}")
    if status == 0:
        liveness(tag)
        return "abort"
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) returned {status} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return "defect"
        return "abort"
    if reject:
        if 200 <= status <= 299:
            DEFECTS.append(f"({tag}) returned {status} where the contract "
                           f"pins a rejection — not rejecting when it "
                           f"should = Type1_IllegalSuccess — "
                           f"raw={str(raw)[:150]}")
            return "defect"
        if 400 <= status <= 499:
            print(f"[{tag}] OK: rejected with {status} (pinned face kept; "
                  f"exact error-code naming printed above, NOT adjudicated "
                  f"— R29: Type2 error-naming has no anchor)")
            return "ok"
        print(f"[{tag}] UNEXPECTED status {status} — neither 2xx nor 4xx; "
              f"cannot adjudicate this face safely")
        return "setup"
    # success face
    if status == 200:
        print(f"[{tag}] OK: 200 success face (pinned: returns 200 ok)")
        return "ok"
    if 200 <= status <= 299:
        print(f"[{tag}] NOTE: 2xx variant {status} accepted as success face")
        return "ok"
    print(f"[{tag}] SETUP face: plainly valid op returned {status} — "
          f"cannot judge state semantics")
    return "setup"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sps15_" + TS + "_"
    C = PFX + "col"
    GHOST = PFX + "nonexistent"   # never created

    IDS = [1, 2, 3]
    ORIG = {"a": 1}

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i), 1.0, 2.0, 3.0],
                "payload": dict(ORIG)} for i in IDS]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 3] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        base = scroll_map("A baseline", C)
        if base is None or set(base.keys()) != set(IDS):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        BASEVEC = {i: vec_of(base[i]) for i in IDS}
        if any(v is None for v in BASEVEC.values()):
            print("SETUP_ERROR: baseline readback missing vectors")
            return "SCRIPT_ERROR"

        # ---- (V1 positive face) valid points-targeted set -> 200 ----
        v1_s, v1_raw = safe_request("POST", "payload_set",
                                    path_params={"collection_name": C},
                                    body={"payload": {"ok": 1},
                                          "points": [1]},
                                    query_params={"wait": "true"})
        r = face("V1 valid set ok=1 on [1]", v1_s, v1_raw, reject=False)
        if r in ("abort", "setup"):
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        time.sleep(0.3)
        m = scroll_map("V1 readback", C)
        if m is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        for i in IDS:
            pl, okp = pay_dict(m.get(i, {}))
            expect = {"a": 1, "ok": 1} if i == 1 else dict(ORIG)
            if not okp or pl != expect:
                DEFECTS.append(f"(V1 state) point {i} payload {pl!r} != "
                               f"{expect!r} — positive-face state mismatch — "
                               f"Type4_StateLogicViolation")
        if not DEFECTS:
            print("[V1 state] OK: point 1 merged to {'a':1,'ok':1}; "
                  "points 2-3 untouched")

        # ---- (V2a both-null, omitted form) must be rejected ----
        v2a_s, v2a_raw = safe_request("POST", "payload_set",
                                      path_params={"collection_name": C},
                                      body={"payload": {"x": 1}},
                                      query_params={"wait": "true"})
        r = face("V2a both-null omitted {\"payload\":{\"x\":1}}",
                 v2a_s, v2a_raw, reject=True)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        v2a_rejected = (r == "ok")

        # ---- (V2b both-null, explicit null form) must be rejected ----
        v2b_s, v2b_raw = safe_request("POST", "payload_set",
                                      path_params={"collection_name": C},
                                      body={"payload": {"x": 1},
                                            "points": None,
                                            "filter": None},
                                      query_params={"wait": "true"})
        r = face("V2b both-null explicit nulls", v2b_s, v2b_raw,
                 reject=True)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (V3 missing collection face) ----
        v3_s, v3_raw = safe_request("POST", "payload_set",
                                    path_params={"collection_name": GHOST},
                                    body={"payload": {"g": 1},
                                          "points": [1]},
                                    query_params={"wait": "true"})
        print(f"[V3 missing-collection set] status={v3_s} raw={v3_raw[:200]}")
        if v3_s == 0:
            liveness("V3")
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if 500 <= v3_s <= 599:
            if liveness("V3"):
                DEFECTS.append(f"(V3) missing-collection set returned {v3_s} "
                               f"with service alive — Type3_RuntimeFailure — "
                               f"raw={v3_raw[:150]}")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if v3_s == 404:
            print("[V3] OK: 404 for a missing collection (pinned face kept)")
        elif 400 <= v3_s <= 499:
            print(f"[V3] 4xx variant {v3_s} — rejection kept the service "
                  f"safe; 404-vs-other naming measured-only (R29)")
        elif 200 <= v3_s <= 299:
            DEFECTS.append(f"(V3) returned {v3_s} for a MISSING collection — "
                           f"success against a nonexistent collection = "
                           f"Type1_IllegalSuccess — raw={v3_raw[:150]}")
        else:
            print(f"[V3] UNEXPECTED status {v3_s} — not adjudicated")

        # ---- (V4 invalid-input face) payload as array ----
        v4_s, v4_raw = safe_request("POST", "payload_set",
                                    path_params={"collection_name": C},
                                    body={"payload": [1, 2], "points": [1]},
                                    query_params={"wait": "true"})
        r = face("V4 invalid input payload=[1,2] on [1]", v4_s, v4_raw,
                 reject=True)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"

        # ---- (V5 both-present, measured-only) ----
        v5_s, v5_raw = safe_request("POST", "payload_set",
                                    path_params={"collection_name": C},
                                    body={"payload": {"both": 1},
                                          "points": [2],
                                          "filter": {"must": [
                                              {"key": "a",
                                               "match": {"value": 1}}]}},
                                    query_params={"wait": "true"})
        print(f"[V5 both-present points+filter (MEASURED-ONLY)] status={v5_s} "
              f"raw={v5_raw[:200]} — selector precedence when both are "
              f"present is NOT pinned by chunk assertions — not adjudicated")

        time.sleep(0.5)

        # ---- (F final state sweep) ----
        mf = scroll_map("F final sweep", C)
        cf = exact_count("F final count", C)
        if mf is None or cf is None:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if cf != 3:
            DEFECTS.append(f"(F) exact count {cf} != 3 — rejected/invalid "
                           f"sets must not delete points — "
                           f"Type4_StateLogicViolation")
        if set(mf.keys()) != set(IDS):
            DEFECTS.append(f"(F) point id set {sorted(mf.keys())} != {IDS} — "
                           f"Type4_StateLogicViolation")
        for i in IDS:
            if i not in mf:
                continue
            pl, okp = pay_dict(mf[i])
            if not okp:
                DEFECTS.append(f"(F) point {i} payload is not an object — "
                               f"Type4_StateLogicViolation")
                continue
            if "x" in pl:
                DEFECTS.append(f"(F) point {i} carries key 'x' from a "
                               f"REJECTED both-null set — partial "
                               f"application after rejection — "
                               f"qdrant_state_payload_set_001 — "
                               f"Type4_StateLogicViolation")
            expect = {"a": 1, "ok": 1} if i == 1 else dict(ORIG)
            # V5 is measured-only: a legal both-present application may
            # legitimately have added 'both' to point 2 — exclude that
            # key from the strict sweep on point 2 only.
            if i == 2 and "both" in pl:
                print(f"[F] point 2 carries measured-only V5 key 'both' "
                      f"(excluded from strict sweep): {pl!r}")
                pl = {k: v for k, v in pl.items() if k != "both"}
            if pl != expect:
                DEFECTS.append(f"(F) point {i} payload {pl!r} != expected "
                               f"{expect!r} — rejected faces must leave zero "
                               f"partial application — "
                               f"Type4_StateLogicViolation")
            if not vec_eq(vec_of(mf[i]), BASEVEC[i]):
                DEFECTS.append(f"(F) point {i} vector changed — "
                               f"Type4_StateLogicViolation")
        if v2a_rejected and not DEFECTS:
            print("[F] OK: all rejection faces left zero partial state; "
                  "positive face state exact")

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
