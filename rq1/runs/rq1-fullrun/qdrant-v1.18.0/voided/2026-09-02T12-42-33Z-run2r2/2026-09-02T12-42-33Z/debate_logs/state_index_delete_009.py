#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_009
# strategy: delete_consistency (Strategy 2 / sequence Pattern C: broken dependency chain)
# endpoint: index+delete
# constraint_ids: qdrant_behavioral_index_delete_001, qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: broken dependency chain (Pattern C) x the 404/200 dichotomy —
  leg 1 (negative): a live collection carries 6 points and a real keyword
  index on f_chain; the COLLECTION is then dropped, so the dependency under
  the index disappears. Three repeated delete_index calls on the dropped
  collection must each return exactly 404 (missing collection face of
  qdrant_behavioral_index_delete_001), reconciled by a describe_collection
  readback that is itself 404. A 200 here means the server operated on a
  ghost resource (Type4); a 5xx means an internal error on a well-defined
  absent-resource face (Type3 with liveness).
  leg 2 (positive): the SAME collection name is recreated (fresh, empty,
  no indexes) — now delete_index for f_chain must return exactly 200
  (idempotent success on a non-existent index, clause A of
  qdrant_state_index_delete_001: the 404 -> 200 transition proves the face
  follows the collection, not a cached index registry); create -> describe
  echo -> delete -> describe absence round-trip closes the chain, with exact
  count 0 on the fresh collection.
  [chunk_index+delete coverage: delete_consistency/chain x
  qdrant_behavioral_index_delete_001 (missing-collection 404 x3 + describe
  reconciliation) + qdrant_state_index_delete_001 (clause A idempotence via
  the recreate transition + describe absence after real delete)]
Oracle: on the dropped collection every delete_index returns exactly 404
  (x3, stable) and describe_collection returns 404; after recreation every
  delete_index returns exactly 200, create_index 2xx, describe echoes
  data_type=keyword for f_chain while the index exists and NO f_chain entry
  after its deletion; exact count on the recreated collection is 0. 200 on
  the dropped collection = Type4 ghost-resource; 5xx/transport with /healthz
  alive = Type3; any other 4xx = Type4 inconsistent disposition.
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

# path keys verified against sorted(rt.PATHS): delete_index/create_index/
# describe_collection/count/upsert_points/drop_collection/create_collection/
# healthz are native qdrant runtime keys (no fabrication)
print(f"[PATHS] index keys present="
      f"{[k for k in ('delete_index', 'create_index', 'describe_collection', 'count', 'drop_collection', 'create_collection') if k in rt.PATHS]}")

FIELD = "f_chain"
N = 6


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    """Transport/5xx branch liveness re-check via the lightweight healthz face."""
    hs, hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={hs} raw={str(hraw)[:120]}")
    return hs == 200


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


def describe_payload_schema(tag, collection):
    """describe_collection readback -> (status, payload_schema map or None)."""
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": collection})
    print(f"[{tag}] describe status={s} raw={str(raw)[:300]}")
    if s != 200:
        return s, None
    b = parse_json(raw)
    res = (b or {}).get("result")
    if not isinstance(res, dict):
        return s, None
    ps = res.get("payload_schema")
    if ps is None:
        return s, {}
    return s, ps if isinstance(ps, dict) else None


def entry_data_type(entry):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        dt = entry.get("data_type")
        if isinstance(dt, str):
            return dt
    return None


def get_count(tag, collection):
    """Exact count via points+count; returns (count_or_None, ok)."""
    s, raw = safe_request("POST", "count", body={"exact": True},
                          path_params={"name": collection})
    print(f"[{tag}] count status={s} raw={str(raw)[:160]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    if not b or not isinstance(b.get("result"), dict) \
            or not isinstance(b["result"].get("count"), int):
        return None, False
    return b["result"]["count"], True


def judge_delete_on(face, s, raw, DEFECTS):
    """Adjudicate one delete against the expected face: 'existing' -> 200,
    'missing' -> 404. Returns True when the face expectation is met."""
    if face == "existing":
        if s in (200, 201):
            return True
        if s == 0 or 500 <= s <= 599:
            if liveness(f"delete existing {s}"):
                DEFECTS.append(
                    f"(existing) idempotent index delete returned {s} while "
                    f"/healthz alive - Type3_RuntimeFailure - raw={str(raw)[:160]}")
        else:
            DEFECTS.append(
                f"(existing) idempotent index delete rejected with HTTP {s} - "
                f"Type4 inconsistent disposition (clause A promises 200) - "
                f"raw={str(raw)[:160]}")
        return False
    # face == "missing": the collection does not exist
    if s == 404:
        return True
    if s == 0 or 500 <= s <= 599:
        if liveness(f"delete missing {s}"):
            DEFECTS.append(
                f"(missing) index delete on dropped collection returned {s} "
                f"while /healthz alive - Type3_RuntimeFailure - should be a "
                f"clean 404 - raw={str(raw)[:160]}")
        return False
    DEFECTS.append(
        f"(missing) index delete on dropped collection returned HTTP {s}, "
        f"expected exactly 404 - " +
        ("Type4 ghost-resource success (200 on absent collection)"
         if s in (200, 201) else "Type4 inconsistent disposition") +
        f" - raw={str(raw)[:160]} (qdrant_behavioral_index_delete_001)")
    return False


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd9_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    pts = [
        {"id": i,
         "vector": [0.05 * i, 0.5, 0.5, 0.5],
         "payload": {FIELD: f"v{i % 2}", "f_plain": i}}
        for i in range(1, N + 1)
    ]

    try:
        # ---- setup: live collection + points + REAL index on FIELD ----
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
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": FIELD,
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[setup create index] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"
        ds, ps = describe_payload_schema("describe after create", C)
        if ds != 200 or ps is None or FIELD not in ps \
                or entry_data_type(ps.get(FIELD)) != "keyword":
            print(f"VERDICT: SCRIPT_ERROR - index echo missing before chain "
                  f"(status={ds}, schema={str(ps)[:160]})")
            return "SCRIPT_ERROR"
        cnt0, ok0 = get_count("baseline count", C)
        if not ok0 or cnt0 != N:
            print(f"VERDICT: SCRIPT_ERROR - baseline count {cnt0} != {N}")
            return "SCRIPT_ERROR"

        # ---- leg 1 (negative): drop the collection, index dependency broken ----
        s, raw = safe_request("DELETE", "drop_collection",
                              path_params={"name": C}, timeout=30)
        print(f"[chain drop collection] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR - drop collection: {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        ds, _ = describe_payload_schema("describe after drop", C)
        if ds != 404:
            DEFECTS.append(
                f"(missing) describe on dropped collection returned {ds}, "
                f"expected 404 - Type4_StateLogicViolation - the collection "
                f"resource must be gone (reconciliation face)")
        for i in range(3):
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": FIELD},
                                  query_params={"wait": "true"}, timeout=30)
            print(f"[chain missing delete {i}] status={s} raw={str(raw)[:200]}")
            judge_delete_on("missing", s, raw, DEFECTS)

        # ---- leg 2 (positive): recreate the SAME name -> faces flip to 200 ----
        s, raw = safe_request("PUT", "create_collection",
                              body={"vectors": {"size": 4, "distance": "Cosine"}},
                              path_params={"name": C}, timeout=30)
        print(f"[chain recreate] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            print(f"VERDICT: SCRIPT_ERROR - recreate: {s} {str(raw)[:200]}")
            return "SCRIPT_ERROR"
        # idempotent delete on the fresh (index-less) collection: 404 -> 200 flip
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FIELD},
                              query_params={"wait": "true"}, timeout=30)
        print(f"[chain recreated idempotent delete] status={s} raw={str(raw)[:200]}")
        judge_delete_on("existing", s, raw, DEFECTS)
        # full create -> echo -> delete -> absence round-trip on the same name
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": FIELD,
                                    "field_schema": {"type": "keyword"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[chain recreated create index] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            DEFECTS.append(
                f"(existing) create_index on recreated collection returned {s} "
                f"- Type4 inconsistent disposition - raw={str(raw)[:160]}")
        else:
            ds, ps = describe_payload_schema("describe recreated indexed", C)
            if ds == 200 and isinstance(ps, dict):
                got = entry_data_type(ps.get(FIELD))
                if got != "keyword":
                    DEFECTS.append(
                        f"(describe) recreated index echo expected keyword, "
                        f"got {got!r} - Type4_StateLogicViolation")
            s, raw = safe_request("DELETE", "delete_index",
                                  path_params={"name": C, "field_name": FIELD},
                                  query_params={"wait": "true"}, timeout=30)
            print(f"[chain recreated real delete] status={s} raw={str(raw)[:200]}")
            judge_delete_on("existing", s, raw, DEFECTS)
            ds, ps = describe_payload_schema("describe recreated post-delete", C)
            if ds == 200 and isinstance(ps, dict) and FIELD in ps:
                DEFECTS.append(
                    f"(describe) deleted index {FIELD} still in payload_schema "
                    f"of the recreated collection - Type4_StateLogicViolation - "
                    f"echo={str(ps)[:200]}")
        cnt1, ok1 = get_count("recreated count", C)
        if ok1 and cnt1 != 0:
            DEFECTS.append(
                f"(count) recreated collection exact count {cnt1} != 0 - "
                f"Type4_StateLogicViolation - recreation must not resurrect "
                f"data from the dropped instance")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("broken dependency chain clean: dropped-collection deletes 404 "
              "stable x3 with describe 404 reconciliation; after recreation "
              "the same delete flips to idempotent 200, index round-trip echoes "
              "and clears correctly, count=0 - NO_DEFECT")
        return "NO_DEFECT"
    finally:
        # cleanup (own data only; failure must not flip the verdict)
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
