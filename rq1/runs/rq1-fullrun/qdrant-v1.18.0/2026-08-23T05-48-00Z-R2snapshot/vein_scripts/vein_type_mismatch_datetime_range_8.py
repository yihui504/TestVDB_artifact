# vein candidate 8 (round 2): datetime range filter silently accepts integer
# values (interpreted as epoch MICROseconds) on an indexed datetime field, with
# no schema/type error; the same integer range on an UNINDEXED datetime field
# never matches anything. Doc says datetime range supports RFC 3339. Both paths
# silently return counts instead of rejecting the wrong type, and the indexed
# vs unindexed semantics diverge for the identical request.
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            print(f"JSON_DECODE_ERROR: {text[:200]}")
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""

C = "vein_r2c8"
try:
    safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
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

    def cnt(key, value):
        flt = {"must": [{"key": key, "range": {"gte": value}}]}
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               json={"filter": flt, "exact": True})
        return (s, b["result"]["count"] if s == 200 else None)

    # epoch microseconds of 2026-01-02T00:00:00Z
    v = 1767312000000000
    s_ts_int, c_ts_int = cnt("ts", v)
    s_raw_int, c_raw_int = cnt("raw", v)
    s_ts_str, c_ts_str = cnt("ts", "2026-01-02T00:00:00Z")
    s_raw_str, c_raw_str = cnt("raw", "2026-01-02T00:00:00Z")
    print(f"indexed ts  int:    status={s_ts_int} count={c_ts_int}")
    print(f"unindexed raw int:  status={s_raw_int} count={c_raw_int}")
    print(f"indexed ts  string: status={s_ts_str} count={c_ts_str}")
    print(f"unindexed raw str:  status={s_raw_str} count={c_raw_str}")

    baseline = (c_ts_str is not None and c_ts_str > 0 and c_raw_str == c_ts_str)
    if baseline and s_ts_int == 200 and s_raw_int == 200 and c_ts_int != c_raw_int:
        print("VERDICT: DEFECT_FOUND — integer datetime range silently accepted "
              f"with divergent semantics: indexed={c_ts_int} vs unindexed={c_raw_int} "
              "(string RFC3339 baseline both agree)")
    elif baseline and (s_ts_int != 200 or s_raw_int != 200):
        print("VERDICT: NO_DEFECT — integer rejected by schema validation")
    else:
        print("VERDICT: NO_DEFECT — baseline not established")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
