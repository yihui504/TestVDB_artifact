#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-1 (vein_type_mismatch_datetime_range_8): datetime
range filter silently accepts integer (UNIX-timestamp) bounds with divergent
indexed/unindexed semantics.

Defect: docs say datetime range supports RFC 3339 only ("You do not need to
convert dates to UNIX timestamps"). An integer bound (epoch microseconds) is
nevertheless silently accepted with 200 on both paths — but diverges: on an
indexed datetime field it returns 193 (matching the string baseline), on an
unindexed datetime field the same request returns 0. Same request, opposite
results, no error on either path.

Source: defects/defect-1.md; log output_vein_type_mismatch_datetime_range_8.log.
"""
import os, sys, json, time
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

C = "mre_q1_dtrange"


def safe_request(method, path, **kwargs):
    try:
        resp = requests.request(method, f"{DB_URL}{path}", timeout=30,
                                headers=HEADERS, **kwargs)
        try:
            body = resp.json() if resp.text else {}
        except Exception:
            body = resp.text
        return resp.status_code, body
    except Exception as e:
        return 0, str(e)


def count_with_range(key, value):
    flt = {"must": [{"key": key, "range": {"gte": value}}]}
    st, body = safe_request("POST", f"/collections/{C}/points/count",
                            json={"filter": flt, "exact": True})
    n = None
    if st == 200 and isinstance(body, dict) and isinstance(body.get("result"), dict):
        n = body["result"].get("count")
    return st, n


def reproduce():
    # Step 1: setup - 200 points, ts (indexed datetime) + raw (unindexed datetime)
    safe_request("DELETE", f"/collections/{C}")
    st, _ = safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    if st not in (200, 201):
        print(f"setup create failed: {st}")
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False
    pts = [{"id": i, "vector": [0.1 * (i % 7), 0.2, 0.3, 1.0],
            "payload": {"ts": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
                        "raw": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z"}}
           for i in range(1, 201)]
    for i in range(0, 200, 100):
        safe_request("PUT", f"/collections/{C}/points?wait=true",
                     json={"points": pts[i:i + 100]})
    # index only ts; raw stays unindexed
    safe_request("PUT", f"/collections/{C}/index?wait=true",
                 json={"field_name": "ts", "field_schema": "datetime"})
    time.sleep(8)

    # Step 2: trigger - integer bound (epoch microseconds of 2026-01-02T00:00:00Z)
    s_ts_int, c_ts_int = count_with_range("ts", 1767312000000000)
    s_raw_int, c_raw_int = count_with_range("raw", 1767312000000000)

    # Step 3: verify against string RFC3339 baseline
    s_ts_str, c_ts_str = count_with_range("ts", "2026-01-02T00:00:00Z")
    s_raw_str, c_raw_str = count_with_range("raw", "2026-01-02T00:00:00Z")
    print(f"indexed ts  int:    status={s_ts_int} count={c_ts_int}")
    print(f"unindexed raw int:  status={s_raw_int} count={c_raw_int}")
    print(f"indexed ts  string: status={s_ts_str} count={c_ts_str}")
    print(f"unindexed raw str:  status={s_raw_str} count={c_raw_str}")

    baseline = (c_ts_str is not None and c_ts_str > 0 and c_raw_str == c_ts_str)
    if baseline and s_ts_int == 200 and s_raw_int == 200 and c_ts_int != c_raw_int:
        print("\nVERDICT: DEFECT_REPRODUCED")
        return True
    print("\nVERDICT: NOT_REPRODUCED "
          "(integer rejected by schema validation, or baseline not established)")
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if reproduce() else 1)
    finally:
        safe_request("DELETE", f"/collections/{C}")
