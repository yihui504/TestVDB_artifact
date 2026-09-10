#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_percol_index_toggle_008
# strategy: index_state
# endpoint: per_collection
# constraint_ids: qdrant_inv_index_toggle_preserves_data_001
# source_url: https://qdrant.tech/documentation/manage-data/payload/
# doc_version: current (site latest; no version archive)
"""
Attack: index_state (Strategy 6: state consistency during async index
  builds, both toggle directions) x qdrant_inv_index_toggle_preserves_data_001
  "creating and deleting a payload index does not alter point data":
  index toggling must change ONLY payload_schema. Mutation justification
  (G6): payload-index creation kicks off an ASYNC background build that
  rewrites segment structures — this build window is exactly where
  implementations have historically dropped or corrupted points, so a
  reader thread hammers scroll+count DURING the toggle. Sequence:
  (A) 10 points with payloads {"city": "c0"/"c1" alternating, "n": i};
  baseline snapshot = scroll with_payload+with_vector (R27 lesson:
  vector oracle is readback-vs-baseline-readback) + exact count 10;
  (B) start a reader thread (loop until told to stop: exact count must
  be 10 and scroll id-set must equal all 10 ids on every iteration);
  (C) PUT /collections/{name}/index {"field_name": "city",
  field_schema keyword} -> 200 (async build starts under live reads);
  (D) poll describe until payload_schema exposes the field (<=15s);
  then verify: snapshot equality — every id present, payload deep-equal
  type-strict, vector equal baseline readback; (E) DELETE
  /collections/{name}/index/city -> 200; poll describe until the field
  is gone; verify snapshot equality AGAIN (both toggle directions) and
  count still 10; (F) reader thread summary — every iteration must have
  seen 200/10-ids/10-count.
  payload_schema readback is shape-tolerant (OpenAPI cross-checked):
  the describe face may materialize it as a list of {name: ...} entries
  or a field-keyed object — both forms are probed, neither is assumed.
  [chunk_per_collection coverage: index_state x
  qdrant_inv_index_toggle_preserves_data_001 (toggle both directions
  under live concurrent reads + double snapshot reconciliation)]
Oracle: index create and delete each -> 200; payload_schema exposes the
  field after create and drops it after delete (still present after
  delete = residue = Type4_StateLogicViolation); the 10-point snapshot
  (ids, type-strict payloads, baseline-readback vectors) is IDENTICAL
  before, between and after the toggle, and exact count stays 10 on
  every reader iteration (a lost/extra point, payload drift or vector
  drift = Type4_StateLogicViolation); any reader or toggle call 5xx
  with /healthz alive = Type3_RuntimeFailure; transport failure ->
  liveness re-check before any verdict.
"""

import os
import sys
import json
import time
import threading
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

N = 10
FIELD = "city"

DEFECTS = []
ABORT = [False]
READER_PROBLEMS = []  # (iteration, kind, detail)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def liveness(tag):
    print(f"[liveness {tag}] healthz probe required")
    _hs, _hraw = safe_request("GET", "healthz", timeout=10)
    print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
    return _hs == 200


def type_strict_eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return type(a) is type(b) and a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return (set(a.keys()) == set(b.keys())
                and all(type_strict_eq(a[k], b[k]) for k in a))
    if isinstance(a, list):
        return (len(a) == len(b)
                and all(type_strict_eq(x, y) for x, y in zip(a, b)))
    return a == b


def vec_eq(a, b, tol=1e-6):
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return False
    return all(isinstance(x, (int, float)) and isinstance(y, (int, float))
               and abs(x - y) <= tol for x, y in zip(a, b))


def scroll_map(tag, coll):
    s, raw = safe_request("POST", "scroll", path_params={"name": coll},
                          body={"limit": 100, "with_payload": True,
                                "with_vector": True})
    print(f"[{tag} scroll] status={s} raw={str(raw)[:160]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        else:
            DEFECTS.append(f"({tag}) scroll transport failure with service "
                           f"alive — Type3_RuntimeFailure")
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) scroll returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
        else:
            ABORT[0] = True
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
        return None
    return {p.get("id"): p for p in pts if isinstance(p, dict)}


def exact_count(tag, coll):
    s, raw = safe_request("POST", "count", path_params={"name": coll},
                          body={"exact": True})
    print(f"[{tag} count] status={s} raw={str(raw)[:160]}")
    if s == 0:
        if not liveness(tag):
            ABORT[0] = True
        return None
    if 500 <= s <= 599:
        if liveness(tag):
            DEFECTS.append(f"({tag}) count returned {s} with service alive "
                           f"— Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return None
    if s != 200:
        return None
    try:
        res = json.loads(raw).get("result")
        cnt = res.get("count") if isinstance(res, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        cnt = None
    return cnt if isinstance(cnt, int) and not isinstance(cnt, bool) else None


def schema_has_field(coll, field):
    """describe -> (reachable, has_field). Shape-tolerant: payload_schema
    may be a list of {name:...} entries or a field-keyed object.
    Transport/5xx describe failures go through the liveness branch —
    they never masquerade as 'field absent'."""
    s, raw = safe_request("GET", "describe_collection",
                          path_params={"name": coll})
    if s == 0 or 500 <= s <= 599:
        if liveness("describe schema"):
            DEFECTS.append("(describe schema) returned "
                           f"{s} with service alive — "
                           "Type3_RuntimeFailure")
        else:
            ABORT[0] = True
        return False, None
    if s != 200:
        return False, None
    try:
        res = json.loads(raw).get("result")
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return False, None
    if not isinstance(res, dict):
        return False, None
    ps = res.get("payload_schema")
    if ps is None:
        return True, False
    if isinstance(ps, dict):
        return True, field in ps
    if isinstance(ps, list):
        return True, any(isinstance(e, dict) and e.get("name") == field
                         for e in ps)
    return True, False


def poll_schema(coll, field, want_present, deadline_s=15.0):
    """Poll describe until the field appears/disappears. True=settled."""
    t0 = time.time()
    last = None
    while time.time() - t0 < deadline_s:
        if ABORT[0]:
            return False
        reachable, has = schema_has_field(coll, field)
        if reachable and has == want_present:
            return True
        last = has
        time.sleep(0.5)
    print(f"[poll schema] field {field!r} settled={want_present} not "
          f"reached in {deadline_s}s (last has={last})")
    return False


def reader_loop(coll, stop_evt):
    """Concurrent reader during the toggle: count must be N and the id set
    complete on EVERY iteration."""
    it = 0
    while not stop_evt.is_set():
        it += 1
        s, raw = safe_request("POST", "count", path_params={"name": coll},
                              body={"exact": True}, timeout=20)
        if s == 0 or 500 <= s <= 599 or s != 200:
            READER_PROBLEMS.append((it, "count_status", f"{s} {str(raw)[:100]}"))
            time.sleep(0.2)
            continue
        try:
            res = json.loads(raw).get("result")
            cnt = res.get("count") if isinstance(res, dict) else None
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            cnt = None
        if cnt != N:
            READER_PROBLEMS.append((it, "count_value", f"{cnt!r}"))
        s2, raw2 = safe_request("POST", "scroll", path_params={"name": coll},
                                body={"limit": 100, "with_payload": False},
                                timeout=20)
        if s2 == 0 or 500 <= s2 <= 599 or s2 != 200:
            READER_PROBLEMS.append((it, "scroll_status", f"{s2}"))
            time.sleep(0.2)
            continue
        try:
            res2 = json.loads(raw2).get("result")
            ids = set(p.get("id") for p in res2.get("points", [])
                      if isinstance(p, dict)) if isinstance(res2, dict) else set()
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            ids = set()
        if ids != set(range(N)):
            READER_PROBLEMS.append((it, "scroll_ids",
                                    f"{sorted(i for i in ids if i is not None)}"))
        time.sleep(0.2)
    print(f"[reader] {it} iterations during toggle")


def snapshot_check(tag, m, base):
    """ids complete + payloads type-strict + vectors vs baseline readback."""
    if m is None:
        return
    if set(m.keys()) != set(range(N)):
        DEFECTS.append(f"({tag}) point id set {sorted(m.keys())} != "
                       f"{list(range(N))} — points lost/added by the index "
                       f"toggle — Type4_StateLogicViolation")
        return
    for i in range(N):
        pl = m[i].get("payload")
        pl = pl if isinstance(pl, dict) else {}
        if not type_strict_eq(pl, base["payloads"][i]):
            DEFECTS.append(f"({tag}) point {i} payload drifted after index "
                           f"toggle: {pl!r} != {base['payloads'][i]!r} — "
                           f"index build must alter ONLY payload_schema — "
                           f"Type4_StateLogicViolation")
        v = m[i].get("vector")
        if not vec_eq(v if isinstance(v, list) else None,
                      base["vectors"][i]):
            DEFECTS.append(f"({tag}) point {i} vector drifted after index "
                           f"toggle (readback-vs-baseline-readback) — "
                           f"Type4_StateLogicViolation")
    if not any(f"({tag})" in d for d in DEFECTS):
        print(f"[{tag}] OK: snapshot identical to baseline "
              f"(ids + payloads + vectors)")


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "sitg8_" + TS + "_"
    C = PFX + "col"
    DIM = 4

    try:
        ok, err = rt.setup_default(C, DIM, "Cosine")
        if not ok:
            print(f"SETUP_ERROR: setup_default failed: {err}")
            return "SCRIPT_ERROR"
        pts = [{"id": i, "vector": [float(i) + 0.1, 0.2, 0.3, 0.4],
                "payload": {"city": f"c{i % 2}", "n": i}} for i in range(N)]
        s, raw = safe_request("PUT", "upsert_points",
                              path_params={"name": C}, body={"points": pts},
                              query_params={"wait": "true"})
        print(f"[A upsert {N}] status={s} raw={raw[:150]}")
        if s != 200 or exact_count("A", C) != N:
            print("SETUP_ERROR: A stage failed")
            return "SCRIPT_ERROR"
        m = scroll_map("A baseline", C)
        if m is None or set(m.keys()) != set(range(N)):
            print("SETUP_ERROR: baseline scroll incomplete")
            return "SCRIPT_ERROR"
        base = {"payloads": {}, "vectors": {}}
        for i in range(N):
            pl = m[i].get("payload")
            base["payloads"][i] = pl if isinstance(pl, dict) else {}
            v = m[i].get("vector")
            base["vectors"][i] = v if isinstance(v, list) else None

        # ---- (B) reader thread starts BEFORE the toggle ----
        stop_evt = threading.Event()
        reader = threading.Thread(target=reader_loop, args=(C, stop_evt))
        reader.start()

        # ---- (C) create index under live reads ----
        s, raw = safe_request("PUT", "create_index",
                              path_params={"name": C},
                              body={"field_name": FIELD,
                                    "field_schema": {"type": "keyword"}})
        print(f"[C index create {FIELD}] status={s} raw={raw[:180]}")
        if s == 0 or 500 <= s <= 599:
            liveness("C create")
            stop_evt.set()
            reader.join(timeout=10)
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            print(f"SETUP_ERROR: index create returned {s}")
            stop_evt.set()
            reader.join(timeout=10)
            return "SCRIPT_ERROR"

        # ---- (D) wait for the async build to register, then reconcile ----
        settled = poll_schema(C, FIELD, want_present=True)
        if not settled and not ABORT[0]:
            DEFECTS.append(f"(D schema) field {FIELD!r} never appeared in "
                           f"describe payload_schema after a 200 index "
                           f"create — Type4_StateLogicViolation")
        else:
            print(f"[D schema] OK: {FIELD} exposed in payload_schema")
        snapshot_check("D after create", scroll_map("D", C), base)

        # ---- (E) delete index, wait for removal, reconcile again ----
        s, raw = safe_request("DELETE", "delete_index",
                              path_params={"name": C, "field_name": FIELD})
        print(f"[E index delete {FIELD}] status={s} raw={raw[:180]}")
        if s == 0 or 500 <= s <= 599:
            liveness("E delete")
            stop_evt.set()
            reader.join(timeout=10)
            return "SCRIPT_ERROR" if not DEFECTS else "DEFECT_FOUND"
        if s != 200:
            print(f"SETUP_ERROR: index delete returned {s}")
            stop_evt.set()
            reader.join(timeout=10)
            return "SCRIPT_ERROR"
        settled = poll_schema(C, FIELD, want_present=False)
        if not settled and not ABORT[0]:
            DEFECTS.append(f"(E schema) field {FIELD!r} still present in "
                           f"payload_schema after a 200 index delete — "
                           f"index residue — Type4_StateLogicViolation")
        else:
            print(f"[E schema] OK: {FIELD} removed from payload_schema")
        snapshot_check("E after delete", scroll_map("E", C), base)
        cnt = exact_count("final", C)
        if cnt is not None and cnt != N:
            DEFECTS.append(f"(final count) exact count {cnt} != {N} after "
                           f"the full index toggle — "
                           f"Type4_StateLogicViolation")

        # ---- (F) reader summary ----
        stop_evt.set()
        reader.join(timeout=30)
        for (it, kind, detail) in READER_PROBLEMS[:10]:
            print(f"[reader problem] iter={it} kind={kind} detail={detail}")
        if READER_PROBLEMS:
            kinds = {}
            for (_, k, _) in READER_PROBLEMS:
                kinds[k] = kinds.get(k, 0) + 1
            if "count_status" in kinds or "scroll_status" in kinds:
                if liveness("reader summary"):
                    DEFECTS.append(f"(reader during toggle) {len(READER_PROBLEMS)} "
                                   f"failed reads with service alive "
                                   f"({kinds}) — Type3_RuntimeFailure")
            if "count_value" in kinds or "scroll_ids" in kinds:
                DEFECTS.append(f"(reader during toggle) inconsistent reads "
                               f"during the index build ({kinds}) — "
                               f"Type4_StateLogicViolation "
                               f"(qdrant_inv_index_toggle_preserves_data_001)")
        else:
            print("[reader] OK: every iteration saw the complete "
                  f"{N}-point set")

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        if ABORT[0]:
            print("ABORT: environment/transport unavailable mid-run")
            return "SCRIPT_ERROR"
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
