#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_optimizations_001
# strategy: delete_consistency
# endpoint: collections+optimizations
# constraint_ids: qdrant_behavioral_collections_optimizations_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-optimizations
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: Strategy 2 (post-DELETE state consistency) against the
  optimizer-status face qdrant_behavioral_collections_optimizations_001
  pins: "existing collection -> HTTP 200 with optimizer status per
  shard; missing collection -> HTTP 404". The optimizations readout is
  therefore a per-collection STATE channel whose verdict must track the
  collection lifecycle exactly over the {name} path:
  (A negative) never-created unique name -> HTTP 404 exactly (the
      assertion's "missing collection" branch — a 200 here reports
      optimizer status for a collection that never existed = a
      phantom readout; a 500 instead of 404 = the face cannot
      express absence).
  (B setup) create the collection -> 200 (setup gate).
  (C positive) live collection -> 200 + result envelope object
      (per-shard status readout). A 404 here = the face lies about a
      live collection's state.
  (D write invariance) upsert 2 points wait=true -> readout must STAY
      200 + envelope (the status channel is invariant under point-level
      CRUD — a 404/500 triggered by "points exist" is a state readout
      breaking under data).
  (E post-delete) drop -> optimizations on the name -> 404 (zombie 200
      after a confirmed delete = delete did not retire the readout).
  (F recreate) recreate the SAME name -> 200 + envelope, and the
      readout must reflect the NEW empty incarnation: if
      result.summary is present its queued_points must be the integer
      0 (a >0 queue on a never-written fresh collection = stale
      optimizer state leaking across incarnations — Type4).
  Shape oracle per the materialized response_shape (result: object;
  result.summary: object {queued_optimizations/queued_segments/
  queued_points/idle_segments: integer}; result.running: array;
  queued/completed/idle_segments: array|null): on every 200 the body
  must be JSON with result an OBJECT; each PRESENT group key is typed
  against the spec (summary object / running list / queued,
  completed, idle_segments list-or-null) — a present-but-wrong-typed
  group is a shape conflict (spec wins; conflict zones measured-only:
  unknown extra keys and absent optional groups are printed, not
  judged).
  [chunk_collections+optimizations coverage: delete_consistency x
   qdrant_behavioral_collections_optimizations_001 (200/404 lifecycle
   channel + envelope shape + clean-slate recreate)]
Oracle: never-created -> HTTP 404; live (after create) -> HTTP 200
  with result an object, invariant under wait=true point upserts;
  after a confirmed drop -> HTTP 404 again (a 200 after delete or on
  a never-created name = Type4_StateLogicViolation phantom readout; a
  404/other non-200 on the live collection = Type4 channel lie);
  after recreate -> 200 with a clean envelope whose summary.
  queued_points (when present) is 0; any present group key typed
  against the spec wrongly = Type4 shape conflict; 5xx = Type3 only
  when /healthz confirms liveness.
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

# optimizations endpoint is not in the runtime PATHS whitelist (verified:
# create/describe/drop/upsert/... are present, optimizations is not) —
# register it VERBATIM from raw_knowledge api_endpoints[].url:
#   {"path": "collections+optimizations", "method": "GET",
#    "url": "/collections/{collection_name}/optimizations"}
rt.PATHS["collection_optimizations"] = "/collections/{collection_name}/optimizations"
print(f"[PATHS] registration check: "
      f"{[k for k in sorted(rt.PATHS) if 'optimizations' in k]}")
if rt.PATHS.get("collection_optimizations") != "/collections/{collection_name}/optimizations":
    print("VERDICT: SCRIPT_ERROR - optimizations URL registration failed")
    sys.exit(2)


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


GROUPS = {"summary", "running", "queued", "completed", "idle_segments"}
SUMMARY_INTS = ("queued_optimizations", "queued_segments",
                "queued_points", "idle_segments")


def check_envelope(raw):
    """Spec-typed envelope check of a 200 optimizations body.
    Returns (defect_note_or_None, measured_notes_list)."""
    notes = []
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return "200 body is not JSON", []
    if not isinstance(b, dict):
        return "200 body is not an object", []
    res = b.get("result")
    if not isinstance(res, dict):
        return (f"200 body result is not an object "
                f"(got {type(res).__name__}) — materialized response_shape "
                f"pins result: object", [])
    for k in res:
        if k not in GROUPS:
            notes.append(f"measured: result has extra key {k!r} "
                         f"(not in spec envelope {sorted(GROUPS)})")
    v = res.get("summary")
    if v is not None:
        if not isinstance(v, dict):
            return ("present result.summary is not an object — "
                    "spec pins summary: object", notes)
        for f in SUMMARY_INTS:
            fv = v.get(f)
            if fv is not None and (not isinstance(fv, int)
                                   or isinstance(fv, bool)):
                return (f"present result.summary.{f} is not an integer "
                        f"(got {fv!r})", notes)
    v = res.get("running")
    if v is not None:
        if not isinstance(v, list):
            return "present result.running is not an array — spec pins array", notes
        for e in v:
            if not isinstance(e, dict):
                return ("present result.running[] entry is not an object "
                        f"(got {type(e).__name__})", notes)
    for k in ("queued", "completed", "idle_segments"):
        v = res.get(k)
        if v is not None and not isinstance(v, list):
            return (f"present result.{k} is not an array or null — "
                    f"spec pins array|null", notes)
    return None, notes


def probe(tag, name, expect_404):
    """One optimizations readout judged on the pinned 200/404 channel.
    Returns True=ok, False=defect recorded, None=abort (env-class)."""
    s, raw = safe_request("GET", "collection_optimizations",
                          path_params={"collection_name": name})
    print(f"[{tag}] status={s} raw={str(raw)[:220]}")
    if s == 0:
        liveness(tag)
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) optimizations returned {s} "
                           f"with service alive — Type3_RuntimeFailure — "
                           f"raw={str(raw)[:150]}")
            return False
        return None
    if expect_404:
        if s == 404:
            print(f"[{tag}] OK: 404 (missing collection branch)")
            return True
        if s == 200:
            DEFECTS.append(f"({tag}) optimizations returned 200 for a "
                           f"MISSING collection (never-created/dropped) — "
                           f"phantom readout — Type4_StateLogicViolation — "
                           f"raw={str(raw)[:150]} "
                           f"(qdrant_behavioral_collections_optimizations_001)")
            return False
        DEFECTS.append(f"({tag}) missing collection produced {s} — the "
                       f"assertion pins HTTP 404 — Type4_StateLogicViolation "
                       f"— raw={str(raw)[:150]}")
        return False
    # expect 200 (collection exists)
    if s == 404:
        DEFECTS.append(f"({tag}) optimizations returned 404 for a LIVE "
                       f"collection — the status readout lies about state — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return False
    if s != 200:
        DEFECTS.append(f"({tag}) optimizations returned {s} for a LIVE "
                       f"collection — assertion pins HTTP 200 — "
                       f"Type4_StateLogicViolation — raw={str(raw)[:150]}")
        return False
    note, notes = check_envelope(raw)
    for n in notes:
        print(f"[{tag}] {n}")
    if note:
        DEFECTS.append(f"({tag}) 200 body shape conflict: {note} — "
                       f"Type4_StateLogicViolation (spec wins) — "
                       f"raw={str(raw)[:200]}")
        return False
    print(f"[{tag}] OK: 200 + result object envelope")
    return True


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sop1_" + TS + "_"
    C = PFX + "col"
    NEVER = PFX + "never_created"
    global DEFECTS
    DEFECTS = []

    try:
        # ---- (A negative) never-created unique name -> 404 ----
        if probe("A never-created", NEVER, expect_404=True) is None:
            return "SCRIPT_ERROR"

        # ---- (B setup) create ----
        b_s, b_raw = safe_request("PUT", "create_collection",
                                  path_params={"name": C},
                                  body={"vectors": {"size": 4,
                                                    "distance": "Cosine"}})
        print(f"[B create] status={b_s} raw={b_raw[:200]}")
        if b_s == 0 or 500 <= b_s <= 599 or b_s not in (200, 201):
            liveness("B")
            print(f"SETUP_ERROR: create returned {b_s} — cannot judge "
                  f"optimizations contract")
            return "SCRIPT_ERROR"

        # ---- (C positive) live collection -> 200 + envelope ----
        if probe("C live", C, expect_404=False) is None:
            return "SCRIPT_ERROR"

        # ---- (D write invariance) point CRUD must not break the channel ----
        pts = [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]},
               {"id": 2, "vector": [0.4, 0.3, 0.2, 0.1]}]
        d_s, d_raw = safe_request("PUT", "upsert_points",
                                  path_params={"name": C},
                                  body={"points": pts},
                                  query_params={"wait": "true"})
        print(f"[D upsert 2] status={d_s} raw={d_raw[:150]}")
        if d_s not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {d_s} — write leg aborted")
            return "SCRIPT_ERROR"
        time.sleep(0.5)
        if probe("D after-upsert", C, expect_404=False) is None:
            return "SCRIPT_ERROR"

        # ---- (E post-delete) drop -> 404 ----
        e_s, e_raw = safe_request("DELETE", "drop_collection",
                                  path_params={"name": C},
                                  query_params={"timeout": "30"})
        print(f"[E drop] status={e_s} raw={e_raw[:150]}")
        if e_s != 200:
            print(f"SETUP_ERROR: drop returned {e_s} — cannot judge "
                  f"post-delete optimizations")
            return "SCRIPT_ERROR"
        if probe("E post-delete", C, expect_404=True) is None:
            return "SCRIPT_ERROR"

        # ---- (F recreate same name) clean-slate readout ----
        f_s, f_raw = safe_request("PUT", "create_collection",
                                  path_params={"name": C},
                                  body={"vectors": {"size": 4,
                                                    "distance": "Cosine"}})
        print(f"[F recreate] status={f_s} raw={f_raw[:150]}")
        if f_s != 200:
            print(f"SETUP_ERROR: recreate returned {f_s} — cannot judge "
                  f"clean-slate readout")
            return "SCRIPT_ERROR"
        if probe("F recreated", C, expect_404=False) is None:
            return "SCRIPT_ERROR"
        # clean-slate: a never-written fresh incarnation must report no
        # queued point work (stale optimizer state across recreate = leak)
        g_s, g_raw = safe_request("GET", "collection_optimizations",
                                  path_params={"collection_name": C})
        print(f"[G clean-slate raw] status={g_s} raw={str(g_raw)[:220]}")
        if g_s == 200:
            note, _notes = check_envelope(g_raw)
            if note:
                DEFECTS.append(f"(G) 200 body shape conflict: {note} — "
                               f"Type4_StateLogicViolation — "
                               f"raw={str(g_raw)[:200]}")
            else:
                try:
                    qp = json.loads(g_raw)["result"].get("summary", {}).get(
                        "queued_points")
                except Exception:
                    qp = None
                if qp is not None:
                    if isinstance(qp, bool) or not isinstance(qp, int):
                        DEFECTS.append(f"(G) summary.queued_points={qp!r} "
                                       f"is not an integer — "
                                       f"Type4_StateLogicViolation")
                    elif qp > 0:
                        DEFECTS.append(f"(G) fresh empty recreated "
                                       f"collection reports "
                                       f"queued_points={qp} > 0 — stale "
                                       f"optimizer state leaking across "
                                       f"incarnations — "
                                       f"Type4_StateLogicViolation — "
                                       f"raw={str(g_raw)[:200]}")
                    else:
                        print(f"[G] OK: clean-slate summary.queued_points=0")
                else:
                    print(f"[G] measured: summary absent or queued_points "
                          f"absent — no clean-slate value to judge")

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
