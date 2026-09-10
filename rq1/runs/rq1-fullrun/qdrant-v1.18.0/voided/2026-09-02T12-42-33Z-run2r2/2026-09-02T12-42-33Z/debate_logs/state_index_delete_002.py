#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_index_delete_002
# strategy: count_consistency
# endpoint: index+delete
# constraint_ids: qdrant_state_index_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/indexes/delete-field-index
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
"""
Attack: count_consistency (Strategy 1: CRUD-then-COUNT, with payload-index
  DELETION as the mutation between the two COUNT observations) x
  qdrant_state_index_delete_001 clause B ("deleting an index does not delete
  the underlying data"). Three upsert batches (10+5+3=18 points) are counted
  at batch granularity, then the integer payload index on f_val is created
  and deleted (wait=true) with exact counts taken at every step: total count
  AND filtered count on the previously-indexed field must be identical
  before the index, with the index, and after its deletion; the scroll
  payload snapshot must be deep-equal across all three phases. A final
  post-delete upsert leg proves the data path itself is unaffected by the
  deletion (new writes land, counts advance, then an idempotent re-delete of
  the already-deleted index still returns 200 without disturbing them).
  [chunk_index+delete coverage: count_consistency x
  qdrant_state_index_delete_001 (clause B at the exact-count layer: total +
  filtered counts invariant across index create/delete; post-delete write
  path)]
Oracle: exact count goes 10 -> 15 -> 18 across the three batches and stays
  exactly 18 before/with/after the payload index toggle; filtered count
  (f_val >= 15) stays exactly 4 across the same three phases and becomes
  exactly 6 after the two post-delete upserts (ids 100,101) which bring the
  total to exactly 20; the idempotent re-delete after those writes returns
  200 and changes no count. Count drift after index deletion (total or
  filtered) = Type4_StateLogicViolation; 4xx on the idempotent re-delete =
  Type1_IllegalSuccess; 5xx/transport while /healthz alive =
  Type3_RuntimeFailure (qdrant_state_index_delete_001)
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


def get_count(tag, collection, flt=None):
    body = {"exact": True}
    if flt is not None:
        body["filter"] = flt
    s, raw = safe_request("POST", "count", body=body,
                          path_params={"name": collection})
    print(f"[{tag}] count status={s} raw={str(raw)[:160]}")
    if s != 200:
        return None, False
    b = parse_json(raw)
    if not b or not isinstance(b.get("result"), dict) \
            or not isinstance(b["result"].get("count"), int):
        return None, False
    return b["result"]["count"], True


def scroll_payloads(tag, collection):
    s, raw = safe_request("POST", "scroll",
                          body={"limit": 100, "with_payload": True},
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


FLT_GTE15 = {"must": [{"key": "f_val", "range": {"gte": 15}}]}


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sidd2_" + TS + "_"
    C = PFX + "col"
    DEFECTS = []

    def batch_points(ids):
        return [{"id": i, "vector": [0.1 + 0.01 * i, 0.2, 0.3, 0.4],
                 "payload": {"f_val": i}} for i in ids]

    try:
        ok, err = rt.setup_default(C, 4)
        if not ok:
            print(f"VERDICT: SCRIPT_ERROR - setup failed: {err}")
            return "SCRIPT_ERROR"

        # ---- phase 0: CRUD counting at batch granularity (10 -> 15 -> 18) ----
        for ids, want in ((range(1, 11), 10), (range(11, 16), 15),
                          (range(16, 19), 18)):
            s, raw = safe_request("PUT", "upsert_points",
                                  body={"points": batch_points(ids)},
                                  path_params={"name": C},
                                  query_params={"wait": "true"})
            print(f"[upsert batch] status={s} raw={str(raw)[:160]}")
            if s not in (200, 201):
                return "SCRIPT_ERROR"
            cnt, okc = get_count(f"count after batch want={want}", C)
            if not okc:
                return "SCRIPT_ERROR"
            if cnt != want:
                DEFECTS.append(
                    f"(count) batch insert counting broken: got {cnt}, "
                    f"expected {want} - Type4_StateLogicViolation")

        cnt_pre, _ = get_count("count pre-index", C)
        f_pre, okf_pre = get_count("filtered pre-index", C, flt=FLT_GTE15)
        snap_pre, oksp = scroll_payloads("scroll pre-index", C)
        if cnt_pre != 18 or not okf_pre or f_pre != 4 or not oksp or len(snap_pre) != 18:
            print(f"VERDICT: SCRIPT_ERROR - baseline cnt={cnt_pre} filt={f_pre} "
                  f"snap={len(snap_pre) if oksp else None}")
            return "SCRIPT_ERROR"

        # ---- phase 1: create the payload index ----
        s, raw = safe_request("PUT", "create_index",
                              body={"field_name": "f_val",
                                    "field_schema": {"type": "integer"}},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[create f_val index] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            return "SCRIPT_ERROR"

        cnt_idx, oki = get_count("count with-index", C)
        f_idx, okfi = get_count("filtered with-index", C, flt=FLT_GTE15)
        if oki and cnt_idx != 18:
            DEFECTS.append(
                f"(count) total count {cnt_idx} != 18 with the payload index "
                f"present - Type4_StateLogicViolation")
        if okfi and f_idx != 4:
            DEFECTS.append(
                f"(count) filtered count {f_idx} != 4 with the payload index "
                f"present - Type4_StateLogicViolation")

        # ---- phase 2: DELETE the index (the mutation under test) ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": "f_val"},
                              query_params={"wait": "true"})
        print(f"[delete f_val index] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if s == 0 or 500 <= s <= 599:
                if not liveness("delete f_val"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(delete f_val) status {s} while /healthz alive - "
                    f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            else:
                DEFECTS.append(
                    f"(delete f_val) existing index delete rejected with "
                    f"HTTP {s} - Type1_IllegalSuccess - raw={str(raw)[:160]}")

        cnt_post, okp = get_count("count post-delete", C)
        f_post, okfp = get_count("filtered post-delete", C, flt=FLT_GTE15)
        snap_post, oksp2 = scroll_payloads("scroll post-delete", C)
        if okp and cnt_post != 18:
            DEFECTS.append(
                f"(count) total count {cnt_post} != 18 after index deletion - "
                f"Type4_StateLogicViolation - index deletion deleted data "
                f"(qdrant_state_index_delete_001 clause B)")
        if okfp and f_post != 4:
            DEFECTS.append(
                f"(count) filtered count {f_post} != 4 after index deletion - "
                f"Type4_StateLogicViolation - the indexed field's data must "
                f"survive its index deletion")
        if oksp2 and snap_post != snap_pre:
            diff = {k for k in set(snap_pre) | set(snap_post)
                    if snap_pre.get(k) != snap_post.get(k)}
            DEFECTS.append(
                f"(payload) index deletion mutated {len(diff)} point "
                f"payload(s): ids={sorted(diff)[:8]} - "
                f"Type4_StateLogicViolation")

        # ---- phase 3: post-delete write path + idempotent re-delete ----
        s, raw = safe_request("PUT", "upsert_points",
                              body={"points": batch_points([100, 101])},
                              path_params={"name": C},
                              query_params={"wait": "true"})
        print(f"[post-delete upsert] status={s} raw={str(raw)[:160]}")
        if s not in (200, 201):
            if s == 0 or 500 <= s <= 599:
                if not liveness("post-delete upsert"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(upsert) status {s} on write after index deletion while "
                    f"/healthz alive - Type3_RuntimeFailure - "
                    f"raw={str(raw)[:160]}")
            else:
                DEFECTS.append(
                    f"(upsert) write rejected with HTTP {s} after index "
                    f"deletion - Type1_IllegalSuccess - raw={str(raw)[:160]}")

        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": "f_val"},
                              query_params={"wait": "true"})
        print(f"[idempotent re-delete] status={s} raw={str(raw)[:200]}")
        if s not in (200, 201):
            if s == 0 or 500 <= s <= 599:
                if not liveness("re-delete f_val"):
                    return "SCRIPT_ERROR"
                DEFECTS.append(
                    f"(re-delete f_val) status {s} while /healthz alive - "
                    f"Type3_RuntimeFailure - raw={str(raw)[:160]}")
            else:
                DEFECTS.append(
                    f"(re-delete f_val) idempotent re-delete rejected with "
                    f"HTTP {s} - Type1_IllegalSuccess - "
                    f"raw={str(raw)[:160]} (qdrant_state_index_delete_001 clause A)")

        cnt_fin, okfin = get_count("count final", C)
        f_fin, okff = get_count("filtered final", C, flt=FLT_GTE15)
        if okfin and cnt_fin != 20:
            DEFECTS.append(
                f"(count) final total count {cnt_fin} != 20 - "
                f"Type4_StateLogicViolation")
        if okff and f_fin != 6:
            DEFECTS.append(
                f"(count) final filtered count {f_fin} != 6 (15,16,17,18,100, "
                f"101) - Type4_StateLogicViolation")

        # ---- summary ----
        print(f"[summary] total=[{cnt_pre},{cnt_idx if oki else None},"
              f"{cnt_post if okp else None},{cnt_fin if okfin else None}] "
              f"filtered=[{f_pre},{f_idx if okfi else None},"
              f"{f_post if okfp else None},{f_fin if okff else None}] "
              f"payload_stable={snap_pre == snap_post if oksp2 else 'n/a'} "
              f"defects={len(DEFECTS)}")
        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        print("CRUD-then-COUNT with index deletion as mutation: totals "
              "10/15/18 stable across the index toggle, filtered count 4 "
              "stable, post-delete writes land (20 total, 6 filtered), "
              "idempotent re-delete 200 - NO_DEFECT")
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
