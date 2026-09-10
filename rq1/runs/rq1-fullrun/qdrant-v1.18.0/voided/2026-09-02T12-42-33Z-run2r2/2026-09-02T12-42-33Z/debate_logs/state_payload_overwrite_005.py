#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_payload_overwrite_005
# strategy: delete_consistency
# endpoint: payload+overwrite
# constraint_ids: qdrant_behavioral_payload_overwrite_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/points/overwrite-payload
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (status-face + post-DELETE state consistency) against
  the behavioral face qdrant_behavioral_payload_overwrite_001:
  "overwrite_payload with valid targets returns HTTP 200; invalid input
  returns 400; missing collection returns 404". The overwrite verdict
  must track the collection lifecycle AND the input-validity branches
  exactly:
  (A negative, 404 branch) never-created unique name, VALID body
      {"payload":{"a":1},"points":[1]} -> HTTP 404 EXACTLY (a 200/201
      here reports success for a collection that never existed =
      phantom ack — Type4; a 5xx instead of 404 = the face cannot
      express absence — Type3 when /healthz alive; any other code
      violates the pinned 404 branch).
  (B setup) create + upsert 2 payload-bearing points
      {"a":1,"b":"two"} -> 200 (gate).
  (C negative, 400 branch — invalid input on a LIVE collection):
      (i) body missing the required "payload" entirely {"points":[1]};
      (ii) payload as a plain string "notobj" instead of object;
      (iii) payload: null;
      (iv) NO selector — neither "points" nor "filter" (the shared
           SetPayload schema pins "points OR filter must identify
           targets; both null is an error" — raw_knowledge state note).
      Each must be REJECTED: 400 pinned; the 4xx family = rejected with
      clear diagnostics (not a defect). A 200/201 = invalid input
      accepted — Type1_IllegalSuccess; a 404 on a live collection =
      face/state inconsistency — Type4; 5xx = Type3 when /healthz
      alive. After each rejection the readback payload must still be
      EXACTLY {"a":1,"b":"two"} (a rejected overwrite must not write).
  (D positive, 200 branch) valid {"payload":{"c":3},"points":[1,2]}
      wait=true -> HTTP 200 EXACTLY, and the 200 is tied to the state
      promise: readback payload of BOTH points EXACTLY {"c":3}
      (a and b removed — set semantics; a 200 with merge semantics =
      phantom ack of the documented behavior).
  (E post-DELETE consistency) DELETE the collection -> 2xx; describe
      confirms 404; the SAME valid overwrite as (D) -> HTTP 404
      EXACTLY again (after-life success = resurrected write channel).
  The 200 envelope is printed informational-only: payload+overwrite
  carries NO pinned response_shape in the contract / published
  OpenAPI, so no envelope oracle is fabricated (R28 standing lesson).
  [chunk_payload+overwrite coverage: delete_consistency x
   qdrant_behavioral_payload_overwrite_001 (404 absent-collection
   branch + 400 invalid-input branches incl. missing selector + 200
   valid branch tied to readback + post-DELETE 404)]
Oracle: valid body on a never-created collection -> HTTP 404 exactly;
  on a live collection each invalid body (missing payload / payload as
  string / payload null / no selector) -> 4xx rejection with state
  unchanged; valid body -> HTTP 200 with both readback payloads
  EXACTLY {"c":3}; after a confirmed collection delete the same valid
  body -> HTTP 404 again. A 200 on absent collection, a 200 on any
  invalid body, a 404 on the live collection, a 200 whose readback is
  not the exact replacement, or a post-delete non-404 =
  Type1/Type4_StateLogicViolation; 5xx counts only when /healthz
  confirms liveness (Type3_RuntimeFailure).
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


def overwrite(coll, body, tag, wait=True):
    """PUT payload+overwrite. Returns (status, raw)."""
    q = {"wait": "true"} if wait else None
    s, raw = safe_request("PUT", "payload_overwrite",
                          path_params={"collection_name": coll},
                          body=body, query_params=q)
    print(f"[{tag}] status={s} raw={str(raw)[:200]}")
    return s, raw


def face_404(tag, status, raw):
    """Adjudicate an absent-collection probe: 404 exact, else defect."""
    if status == 404:
        print(f"[{tag}] OK: 404 as pinned")
        return
    if status == 0:
        liveness(tag)
        DEFECTS.append(f"({tag}) transport failure on absent-collection "
                       f"probe — raw={str(raw)[:120]}")
        return
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) 5xx ({status}) instead of pinned 404 on "
                           f"an absent collection — the face cannot express "
                           f"absence — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
        return
    if 200 <= status <= 299:
        DEFECTS.append(f"({tag}) {status} on a collection that NEVER existed "
                       f"— phantom ack — Type4_StateLogicViolation — "
                       f"raw={str(raw)[:150]}")
        return
    DEFECTS.append(f"({tag}) status {status} violates the pinned 404 branch "
                   f"— Type4_StateLogicViolation — raw={str(raw)[:150]}")


def face_reject(tag, status, raw, why):
    """Adjudicate an invalid-input probe: 4xx family = correct rejection."""
    if status in (400, 422):
        print(f"[{tag}] OK: rejected with {status} ({why})")
        return
    if status == 0:
        liveness(tag)
        DEFECTS.append(f"({tag}) transport failure on invalid-input probe — "
                       f"raw={str(raw)[:120]}")
        return
    if 500 <= status <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) 5xx ({status}) on invalid input ({why}) "
                           f"with service alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
        return
    if status == 404:
        DEFECTS.append(f"({tag}) 404 on a LIVE collection for invalid input "
                       f"({why}) — face/state inconsistency — "
                       f"Type4_StateLogicViolation")
        return
    if 200 <= status <= 299:
        DEFECTS.append(f"({tag}) invalid input ACCEPTED with {status} "
                       f"({why}) — Type1_IllegalSuccess — "
                       f"raw={str(raw)[:150]}")
        return
    DEFECTS.append(f"({tag}) status {status} on invalid input ({why}) — "
                   f"not a clear rejection — Type4_StateLogicViolation — "
                   f"raw={str(raw)[:150]}")


def scroll_payloads(tag, coll):
    """scroll -> {id: payload-dict} (None payload -> {}), or None on abort."""
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": 10, "with_payload": True})
    print(f"[{tag} scroll] status={s} raw={str(raw)[:160]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) scroll returned {s} with service alive "
                           f"— Type3_RuntimeFailure — raw={str(raw)[:150]}")
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
        print(f"SETUP_ERROR: scroll result.points missing")
        return None
    out = {}
    for p in pts:
        if not isinstance(p, dict):
            continue
        pl = p.get("payload")
        out[p.get("id")] = dict(pl) if isinstance(pl, dict) else None
    return out


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "spo5_" + TS + "_"
    C = PFX + "col"
    GHOST = PFX + "ghost"   # never created in this run

    VALID_BODY = {"payload": {"a": 1}, "points": [1]}

    try:
        # ---- (A negative: 404 branch on a never-created collection) ----
        s, raw = overwrite(GHOST, VALID_BODY, "A ghost overwrite")
        face_404("A ghost overwrite", s, raw)

        # ---- (B setup) ----
        ok, err = rt.setup_default(C, 4, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        u_s, u_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": [
                                      {"id": 1, "vector": [1.0, 1.0, 1.0, 1.0],
                                       "payload": {"a": 1, "b": "two"}},
                                      {"id": 2, "vector": [2.0, 1.0, 1.0, 1.0],
                                       "payload": {"a": 1, "b": "two"}}]},
                                  query_params={"wait": "true"})
        print(f"[B upsert] status={u_s} raw={u_raw[:150]}")
        if u_s == 0 or 500 <= u_s <= 599 or u_s not in (200, 201):
            liveness("B")
            return "SCRIPT_ERROR"

        # ---- (C negative: 400 branch on the live collection) ----
        invalid_cases = [
            ("C1 missing 'payload'", {"points": [1]},
             "required 'payload' absent from body"),
            ("C2 payload as string", {"payload": "notobj", "points": [1]},
             "'payload' must be object, got string"),
            ("C3 payload null", {"payload": None, "points": [1]},
             "'payload' is required; null is not an object"),
            ("C4 no selector", {"payload": {"a": 2}},
             "neither 'points' nor 'filter' identifies targets"),
        ]
        for tag, body, why in invalid_cases:
            s, raw = overwrite(C, body, tag)
            face_reject(tag, s, raw, why)
            if 200 <= s <= 299:
                # accepted-invalid mutated state? readback catches it
                pls = scroll_payloads(tag + " readback", C)
                if pls is not None:
                    for pid in (1, 2):
                        if pls.get(pid) not in ({"a": 1, "b": "two"}, None):
                            DEFECTS.append(f"({tag}) accepted-invalid body ALSO "
                                           f"mutated point {pid}: "
                                           f"{pls.get(pid)!r} — "
                                           f"Type4_StateLogicViolation")
            else:
                # rejected op must not have written anything
                pls = scroll_payloads(tag + " state-check", C)
                if pls is not None and (pls.get(1) not in ({"a": 1, "b": "two"}, None)
                                        or pls.get(2) not in ({"a": 1, "b": "two"}, None)):
                    DEFECTS.append(f"({tag}) a REJECTED overwrite still mutated "
                                   f"state: {pls!r} — Type4_StateLogicViolation")

        # ---- (D positive: 200 branch tied to state) ----
        s, raw = overwrite(C, {"payload": {"c": 3}, "points": [1, 2]},
                           "D valid overwrite")
        if s == 0:
            liveness("D")
            return "SCRIPT_ERROR"
        if 500 <= s <= 599:
            if liveness("D"):
                DEFECTS.append(f"(D valid overwrite) 5xx ({s}) on plainly "
                               f"valid input with service alive — "
                               f"Type3_RuntimeFailure — raw={str(raw)[:150]}")
            return "DEFECT_FOUND" if DEFECTS else "SCRIPT_ERROR"
        if s != 200:
            DEFECTS.append(f"(D valid overwrite) plainly valid body on a live "
                           f"collection returned {s}, not the pinned 200 — "
                           f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        if 200 <= s <= 299:
            try:
                b = json.loads(raw) if raw else {}
                print(f"[D] 200 envelope keys={sorted(b.keys()) if isinstance(b, dict) else '?'} "
                      f"result={str(b.get('result'))[:80] if isinstance(b, dict) else '?'} "
                      f"(informational — no pinned response_shape)")
            except (json.JSONDecodeError, ValueError, TypeError):
                print(f"[D] 200 body not JSON (informational) — {str(raw)[:120]}")
            time.sleep(0.4)
            pls = scroll_payloads("D readback", C)
            if pls is None:
                return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
            for pid in (1, 2):
                got = pls.get(pid)
                if got != {"c": 3}:
                    DEFECTS.append(f"(D readback) point {pid} payload {got!r} "
                                   f"!= EXACT replacement {{'c': 3}} — the 200 "
                                   f"ack must reflect documented set semantics "
                                   f"(a,b removed) — Type4_StateLogicViolation")
                else:
                    print(f"[D readback] OK: point {pid} payload exactly {{'c': 3}}")

        # ---- (E post-DELETE consistency) ----
        d_s, d_raw = safe_request("DELETE", "drop_collection",
                                  path_params={"name": C})
        print(f"[E drop] status={d_s} raw={str(d_raw)[:160]}")
        if d_s != 200 and not (200 <= d_s <= 299):
            if d_s == 0:
                liveness("E drop")
            print(f"SETUP_ERROR: drop returned {d_s} — cannot run post-delete "
                  f"face check")
            return "SCRIPT_ERROR"
        time.sleep(0.3)
        g_s, g_raw = safe_request("GET", "describe_collection",
                                  path_params={"name": C})
        print(f"[E describe-after-drop] status={g_s} raw={str(g_raw)[:160]}")
        if g_s != 404:
            DEFECTS.append(f"(E) describe after confirmed drop returned {g_s}, "
                           f"not 404 — drop not effective — "
                           f"Type4_StateLogicViolation")
        s, raw = overwrite(C, {"payload": {"c": 3}, "points": [1, 2]},
                           "E post-delete overwrite")
        face_404("E post-delete overwrite", s, raw)

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
