#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_004
# strategy: index_state
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: index_state (Strategy 6: state consistency across an index-state
  transition, with DELETION as the mutation) x
  qdrant_state_index_delete_001 clause B ("deleting an index does not delete
  the underlying data") observed at the READ-PATH layer rather than raw
  counts: a keyword index on f_city is created and then deleted while the
  identical deterministic read set (filtered scroll with payload on
  f_city=berlin; exact filtered counts for f_city=berlin / f_city=paris /
  compound f_city=berlin AND f_score>=8) is captured at three checkpoints -
  P0 no index (full-scan filtering), P1 index present (describe echo
  verified), P2 index deleted (describe absence verified). A payload index
  is an accelerator, not a semantics change, so all three read sets must be
  IDENTICAL; any divergence after the deletion is data loss visible through
  the query path. Plain vector search is deliberately excluded - HNSW
  approximation/non-deterministic tie-breaking is a documented by-design
  behavior per the threat model, and scroll/count are the deterministic
  faces.
  [chunk_index+delete coverage: index_state x
  qdrant_state_index_delete_001 (clause B at the read-path layer: filter
  scroll + 3 exact filtered counts identical across no-index/index/deleted)]
Oracle: describe shows f_kw index present (data_type keyword) at P1 and
  absent at P2; the filtered scroll snapshot (id set AND payloads) and all
  three exact filtered counts (berlin=8, paris=7, compound=4) are identical
  at P0, P1 and P2; a mid-lifecycle non-mutating control delete of the
  never-indexed f_ctrl field returns 200 without changing any read. Diverged
  scroll id set / payload, or any filtered count differing across
  checkpoints after the index deletion = Type4_StateLogicViolation; 4xx on
  the control delete = Type1_IllegalSuccess; 5xx/transport while /healthz
  alive = Type3_RuntimeFailure (qdrant_state_index_delete_001)
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

print(f"[PATHS] index keys present="
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'count', 'scroll') if k in rt.PATHS]}")

N = 15
FLT_BERLIN = {"must": [{"key": "f_city", "match": {"value": "berlin"}}]}
FLT_PARIS = {"must": [{"key": "f_city", "match": {"value": "paris"}}]}
FLT_COMPOUND = {"must": [
    {"key": "f_city", "match": {"value": "berlin"}},
    {"key": "f_score", "range": {"gte": 8}},
]}
# berlin on odd ids 1..15 -> 8; paris on even ids 2..14 -> 7
EXPECT_BERLIN = len([i for i in range(1, N + 1) if i % 2 == 1])
EXPECT_PARIS = len([i for i in range(1, N + 1) if i % 2 == 0])
EXPECT_COMPOUND = len([i for i in range(1, N + 1)
                       if i % 2 == 1 and i >= 8])


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def get_count(tag, collection, flt):
    s, raw = safe_request("POST", "count", body={"exact": True, "filter": flt},
                          path_params={"name": collection})
    print(f"[{tag}] count status={s} raw={str(raw)[:160]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    if not b or not isinstance(b.get("result"), dict) \
            or not isinstance(b["result"].get("count"), int):
        return None, False
    return b["result"]["count"], True


def scroll_filtered(tag, collection, flt):
    """Filtered scroll snapshot: id -> payload for the matching set."""
    s, raw = safe_request("POST", "scroll",
                          body={"limit": 100, "with_payload": True,
                                "filter": flt},
                          path_params={"name": collection})
    print(f"[{tag}] scroll status={s} raw={str(raw)[:200]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict) or not isinstance(res.get("points"), list):
        return None, False
    snap = {}
    for p in res["points"]:
        if isinstance(p, dict) and "id" in p:
            snap[p["id"]] = p.get("payload")
    return snap, True


def describe_payload_schema(tag, collection):
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": collection})
    print(f"[{tag}] describe status={s} raw={str(raw)[:300]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict):
        return None, False
    ps = res.get("payload_schema")
    if ps is None:
        return {}, True
    if not isinstance(ps, dict):
        return None, False
    return ps, True


def entry_data_type(entry):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        dt = entry.get("data_type")
        if isinstance(dt, str):
            return dt
    return None


def read_set(tag, C, DEFECTS):
    """Capture the deterministic read set: (scroll snapshot, counts triple)."""
    snap, oks = scroll_filtered(f"{tag} scroll berlin", C, FLT_BERLIN)
    cb, okb = get_count(f"{tag} count berlin", C, FLT_BERLIN)
    cp, okp = get_count(f"{tag} count paris", C, FLT_PARIS)
    cc, okc = get_count(f"{tag} count compound", C, FLT_COMPOUND)
    if not (oks and okb and okp and okc):
        # read-path failure on an existing collection: healthz-gated
        alive = liveness(f"{tag} read face")
        for lbl, st in (("scroll", oks), ("berlin", okb),
                        ("paris", okp), ("compound", okc)):
            if not st:
                if alive:
                    DEFECTS.append(
                        f"({tag}) read face {lbl} failed on an existing "
                        f"collection while /healthz alive - "
                        f"Type3_RuntimeFailure (see raw above)")
                else:
                    print(f"NOTE: {tag} face {lbl} failed and /healthz "
                          f"dead - transport-class, not adjudicated")
        return None
    if cb != EXPECT_BERLIN or cp != EXPECT_PARIS or cc != EXPECT_COMPOUND:
        DEFECTS.append(
            f"({tag}) filtered counts wrong: berlin={cb} want "
            f"{EXPECT_BERLIN}, paris={cp} want {EXPECT_PARIS}, "
            f"compound={cc} want {EXPECT_COMPOUND} - "
            f"Type4_StateLogicViolation")
    return {"snap": snap, "berlin": cb, "paris": cp, "compound": cc}


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd4_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    pts = [
        {"id": i,
         "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
         "payload": {"f_city": "berlin" if i % 2 == 1 else "paris",
                     "f_score": i}}
        for i in range(1, N + 1)
    ]

    try:
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"
        s, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup upsert] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        # ---- P0: no index (full-scan filtering) ----
        p0 = read_set("P0", C, DEFECTS)
        if p0 is None:
            print("VERDICT: SCRIPT_ERROR - P0 read set incomplete")
            return "SCRIPT_ERROR"
        if len(p0["snap"]) != EXPECT_BERLIN:
            print(f"VERDICT: SCRIPT_ERROR - P0 scroll returned "
                  f"{len(p0['snap'])} berlin points, want {EXPECT_BERLIN}")
            return "SCRIPT_ERROR"

        # mid-lifecycle control: delete a never-indexed field (clause A face)
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": "f_ctrl"},
                              query_params={"wait": "true"})
        print(f"[P0 control delete f_ctrl] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if s == 0 or 500 <= s <= 599:
                if not liveness("control delete f_ctrl"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(control delete f_ctrl) status {s} while /healthz "
                    f"alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
            else:
                DEFECTS.append(
                    f"(control delete f_ctrl) idempotent delete rejected "
                    f"with HTTP {s} - Type1_IllegalSuccess - "
                    f"raw={str(raw)[:160]}")

        # ---- P1: index present ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": "f_city",
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[create f_city index] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"
        ps1, okps1 = describe_payload_schema("describe P1", C)
        if not okps1:
            return "SCRIPT_ERROR"
        got = entry_data_type(ps1.get("f_city"))
        if ps1.get("f_city") is None or got != "keyword":
            DEFECTS.append(
                f"(describe P1) f_city index echo wrong: {got!r} - "
                f"Type4_StateLogicViolation - echo={str(ps1.get('f_city'))[:160]}")
        p1 = read_set("P1", C, DEFECTS)

        # ---- P2: index deleted (the mutation) ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": "f_city"},
                              query_params={"wait": "true"})
        print(f"[delete f_city index] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if s == 0 or 500 <= s <= 599:
                if not liveness("delete f_city"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(delete f_city) status {s} while /healthz alive - "
                    f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            else:
                DEFECTS.append(
                    f"(delete f_city) existing index delete rejected with "
                    f"HTTP {s} - Type1_IllegalSuccess - raw={str(raw)[:160]}")
        ps2, okps2 = describe_payload_schema("describe P2", C)
        if okps2 and "f_city" in ps2:
            DEFECTS.append(
                f"(describe P2) deleted f_city index still present - "
                f"Type4_StateLogicViolation - echo={str(ps2.get('f_city'))[:160]}")
        p2 = read_set("P2", C, DEFECTS)

        # ---- identity across checkpoints ----
        for name, px in (("P1", p1), ("P2", p2)):
            if px is None:
                continue
            if px["snap"] != p0["snap"]:
                diff_ids = sorted(set(px["snap"]) ^ set(p0["snap"]))[:8]
                DEFECTS.append(
                    f"({name}) filtered scroll set diverged from P0: "
                    f"sym-diff ids={diff_ids} - Type4_StateLogicViolation "
                    f"- read path changed across an index-state transition")
            if (px["berlin"], px["paris"], px["compound"]) != \
                    (p0["berlin"], p0["paris"], p0["compound"]):
                DEFECTS.append(
                    f"({name}) filtered counts diverged from P0: "
                    f"{(px['berlin'], px['paris'], px['compound'])} vs "
                    f"{(p0['berlin'], p0['paris'], p0['compound'])} - "
                    f"Type4_StateLogicViolation")

        # ---- summary ----
        print(f"[summary] berlin/paris/compound = "
              f"P0:{(p0['berlin'], p0['paris'], p0['compound'])} "
              f"P1:{(p1['berlin'], p1['paris'], p1['compound']) if p1 else None} "
              f"P2:{(p2['berlin'], p2['paris'], p2['compound']) if p2 else None} "
              f"scroll_sets_equal="
              f"P1:{p1['snap'] == p0['snap'] if p1 else 'n/a'} "
              f"P2:{p2['snap'] == p0['snap'] if p2 else 'n/a'} "
              f"defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("read-path identity across the index toggle: identical filtered "
              "scroll snapshot and identical exact filtered counts at "
              "no-index / indexed / deleted checkpoints; control delete 200; "
              "no schema residue - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
            print(f"[cleanup] dropped {C}")
        except Exception as e:
            print(f"[cleanup] drop {C} failed (ignored): {e}")


if __name__ == "__main__":
    try:
        _v = main()
    except Exception:
        import traceback
        traceback.print_exc()
        _v = "SCRIPT_ERROR"
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
