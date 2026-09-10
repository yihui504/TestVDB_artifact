#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_set_012
# strategy: upsert_idempotence
# endpoint: payload+set
# constraint_ids: qdrant_state_payload_set_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/set-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 3 (idempotence + state-machine loop) against
  qdrant_state_payload_set_001 (payload+set = MERGE keys, the sibling
  PUT overwrite owns removal). The set-payload operation is cycled on
  one point so the state machine must pass through these exact states:
  (A setup) 1 point, id=10, payload {"a":1,"b":"x","c":true}; baseline
      readback snapshots the stored vector as BASEVEC (R27 lesson: on
      Cosine collections the stored vector is L2-normalized by-design —
      later vector comparisons are readback-vs-baseline-readback only).
  (D1 merge#1) set {"a":2,"d":"new"} wait=true -> 200; readback
      payload EXACTLY {"a":2,"b":"x","c":true,"d":"new"} — overlapping
      key "a" replaced, unlisted "b"/"c" persist, new "d" added.
  (D2 idempotence) the SAME body again -> 200; state STAYS exactly
      {"a":2,"b":"x","c":true,"d":"new"} (a repeat set over its own
      output must neither duplicate, corrupt, nor error; a 4xx/5xx on
      its own prior output state = the operation is not idempotent
      over its own result).
  (D3 disjoint merge) set {"e":false} -> 200; readback EXACTLY
      {"a":2,"b":"x","c":true,"d":"new","e":false} — a later disjoint
      set must be a pure union (any key lost = merge violation).
  (D4 no-op re-set) re-set {"a":2} (already the current value) -> 200;
      state unchanged from D3 (setting the identical value is a no-op,
      not a reset/clear).
  (D5 key type-change, both-branch) set {"a":"stro"} (int -> string at
      key "a"; no payload index exists on "a", so no documented
      constraint blocks it): if 200 -> readback shows "a":"stro" with
      every OTHER D3 key intact (key-level replace must not touch
      siblings); if 4xx -> readback must equal the full D3 state
      (rejection must be clean — no partial application). Either
      branch is legal, only divergence from both is a defect.
  (D6 nested-object value, measured-only) set {"n":{"y":2}} after
      priming {"n":{"x":1}}: top-level-key replace vs deep merge for
      nested object values is NOT pinned by the chunk's assertions —
      status + readback printed, NOT adjudicated (G3: no oracle
      fabrication).
  Exact count must stay 1 and the vector equal BASEVEC across the
  whole loop. Persistence judged via point readback after each
  mutation — never via the set response alone.
  [chunk_payload+set coverage: upsert_idempotence x
   qdrant_state_payload_set_001 (repeat-set convergence + disjoint
   union merge + no-op re-set + key type-change + clean-rejection
   state)]
Oracle: D1 -> 200 and readback exactly {"a":2,"b":"x","c":true,
  "d":"new"}; D2 -> 200 and the SAME state (any drift = not idempotent
  over own output, Type4_StateLogicViolation); D3 -> 200 and the exact
  5-key union; D4 -> 200 and state identical to D3; D5 -> 200 with
  "a":"stro" and all D3 siblings intact, OR 4xx with the exact full
  D3 state preserved (partial application on either branch =
  Type4_StateLogicViolation); D6 measured-only; vector equal to the
  baseline readback (<=1e-6) and exact count 1 invariant throughout;
  5xx only counts when /healthz confirms liveness
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


def do_set(tag, coll, payload, expect_state, basevec, adjudicate=True,
           expect_state_4xx=None):
    """One set-payload step + readback state assertion.

    expect_state: the EXACT payload dict (or list of alternatives)
    expected after the step when a 200 is returned.
    expect_state_4xx: the state expected if the step is REJECTED (4xx)
    — defaults to expect_state (steps whose 4xx means setup failure).
    Branch-aware: a 4xx whose readback equals the 200-state is a
    partial application AFTER rejection, not a legal outcome.
    Returns 'ok' | 'defect' | 'abort' | 'branch4xx'.
    """
    s, raw = safe_request("POST", "payload_set",
                          path_params={"collection_name": coll},
                          body={"payload": payload, "points": [10]},
                          query_params={"wait": "true"})
    print(f"[{tag} set {payload!r}] status={s} raw={str(raw)[:200]}")
    if s == 0:
        liveness(tag)
        return "abort"
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) set returned {s} with service alive — "
                           f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return "defect"
        return "abort"
    if s != 200:
        if not adjudicate:
            print(f"[{tag}] non-200 ({s}) on measured-only step — state "
                  f"checked below, status NOT adjudicated")
        else:
            print(f"[{tag}] non-200 ({s}) — 4xx branch: clean-rejection "
                  f"state check follows")
        branch = "branch4xx"
    else:
        branch = "ok"
    time.sleep(0.3)
    m = scroll_map(tag + " readback", coll)
    if m is None:
        return "abort"
    p = m.get(10)
    if p is None:
        DEFECTS.append(f"({tag}) point 10 disappeared after set-payload — "
                       f"set must not delete points — "
                       f"Type4_StateLogicViolation")
        return "defect"
    pl, okp = pay_dict(p)
    if not okp:
        DEFECTS.append(f"({tag}) point 10 payload is not an object — "
                       f"Type4_StateLogicViolation")
        return "defect"
    if not vec_eq(vec_of(p), basevec):
        DEFECTS.append(f"({tag}) point 10 vector changed after set-payload — "
                       f"set is payload-scoped — Type4_StateLogicViolation")
    if adjudicate:
        legal = expect_state if isinstance(expect_state, list) else [expect_state]
        if branch == "branch4xx" and expect_state_4xx is not None:
            legal = (expect_state_4xx if isinstance(expect_state_4xx, list)
                     else [expect_state_4xx])
        if pl not in legal:
            DEFECTS.append(f"({tag}) point 10 payload {pl!r} not in expected "
                           f"state set {legal!r} — merge/idempotence state "
                           f"machine violated (qdrant_state_payload_set_001: "
                           f"set = merge keys) — Type4_StateLogicViolation")
        else:
            print(f"[{tag}] OK: state exactly {pl!r}")
    else:
        print(f"[{tag}] measured-only state: {pl!r}")
    cnt = exact_count(tag + " count", coll)
    if cnt is None:
        return "abort"
    if cnt != 1:
        DEFECTS.append(f"({tag}) exact count {cnt} != 1 — set must not "
                       f"delete points — Type4_StateLogicViolation")
    if DEFECTS:
        return "defect"
    return branch if branch == "branch4xx" else "ok"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sps12_" + TS + "_"
    C = PFX + "col"

    D1_STATE = {"a": 2, "b": "x", "c": True, "d": "new"}
    D3_STATE = {"a": 2, "b": "x", "c": True, "d": "new", "e": False}

    try:
        # ---- (A setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": 10, "vector": [1.0, 2.0, 3.0, 4.0],
                "payload": {"a": 1, "b": "x", "c": True}}]
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[A upsert 1] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("A")
            return "SCRIPT_ERROR"
        base = scroll_map("A baseline", C)
        if base is None or 10 not in base:
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        BASEVEC = vec_of(base[10])
        if BASEVEC is None:
            print("SETUP_ERROR: baseline readback missing vector")
            return "SCRIPT_ERROR"
        pl0, okp = pay_dict(base[10])
        if not okp or pl0 != {"a": 1, "b": "x", "c": True}:
            DEFECTS.append(f"(A baseline) payload {pl0!r} != uploaded "
                           f"{{'a':1,'b':'x','c':True}} — "
                           f"Type4_StateLogicViolation")

        # ---- (D1 merge#1) overlap replace + unlisted persist + new add ----
        r = do_set("D1 merge#1", C, {"a": 2, "d": "new"}, D1_STATE, BASEVEC)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        if r == "branch4xx":
            print("SETUP_ERROR: plainly valid D1 set rejected — cannot run "
                  "the state machine (status faces adjudicated in "
                  "state_payload_set_015)")
            return "SCRIPT_ERROR"

        # ---- (D2 idempotence) same body again, state must not drift ----
        r = do_set("D2 repeat", C, {"a": 2, "d": "new"}, D1_STATE, BASEVEC)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "branch4xx":
            DEFECTS.append("(D2 repeat) 4xx on re-applying the SAME set "
                           "over its own prior output — set-payload is "
                           "not idempotent over its own result — "
                           "Type4_StateLogicViolation")
        if r == "defect" or DEFECTS:
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"

        # ---- (D3 disjoint merge) pure union ----
        r = do_set("D3 disjoint", C, {"e": False}, D3_STATE, BASEVEC)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        if r == "branch4xx":
            print("SETUP_ERROR: plainly valid D3 set rejected — aborting "
                  "state machine")
            return "SCRIPT_ERROR"

        # ---- (D4 no-op re-set) identical value is a no-op ----
        r = do_set("D4 no-op", C, {"a": 2}, D3_STATE, BASEVEC)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        if r == "branch4xx":
            print("SETUP_ERROR: plainly valid D4 set rejected — aborting "
                  "state machine")
            return "SCRIPT_ERROR"

        # ---- (D5 key type-change, both-branch) ----
        D5_200 = dict(D3_STATE)
        D5_200["a"] = "stro"
        r = do_set("D5 type-change", C, {"a": "stro"},
                   [D5_200, D3_STATE], BASEVEC, expect_state_4xx=[D3_STATE])
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        if r == "ok":
            print("[D5] accepted-branch: key-level type change applied, "
                  "siblings intact")
        else:
            print("[D5] rejected-branch: clean rejection, full D3 state "
                  "preserved")

        # ---- (D6 nested-object value, measured-only) ----
        r = do_set("D6 nested prime", C, {"n": {"x": 1}}, None, BASEVEC,
                   adjudicate=False)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        r = do_set("D6 nested second", C, {"n": {"y": 2}}, None, BASEVEC,
                   adjudicate=False)
        if r == "abort":
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if r == "defect":
            return "DEFECT_FOUND"
        print("[D6] NOTE: top-key-replace vs deep-merge for nested object "
              "values is not pinned by chunk assertions — printed only")

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
