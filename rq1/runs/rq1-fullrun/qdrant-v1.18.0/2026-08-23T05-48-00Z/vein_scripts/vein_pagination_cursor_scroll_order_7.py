# vein candidate 7 (round 2): scroll with order_by never paginates —
# next_page_offset is always null even when limit < total points, so
# page-by-page walking silently truncates the result set. Control: same
# scroll without order_by returns next_page_offset correctly.
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

C = "vein_r2c7"
N = 200
try:
    safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    pts = [{"id": i, "vector": [0.1 * (i % 7), 0.2, 0.3, 1.0],
            "payload": {"num": i * 3, "ts": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z"}}
           for i in range(1, N + 1)]
    for i in range(0, N, 100):
        safe_request("PUT", f"/collections/{C}/points?wait=true",
                     json={"points": pts[i:i + 100]})
    safe_request("PUT", f"/collections/{C}/index?wait=true",
                 json={"field_name": "ts", "field_schema": "datetime"})
    time.sleep(8)

    # walk with order_by
    total_ob, off, seen = 0, None, set()
    for _ in range(10):
        body = {"limit": 70, "with_payload": False,
                "order_by": {"key": "ts", "direction": "desc"}}
        if off is not None:
            body["offset"] = off
        s, b, _ = safe_request("POST", f"/collections/{C}/points/scroll", json=body)
        if s != 200 or b is None:
            break
        r = b["result"]
        total_ob += len(r["points"])
        seen.update(p["id"] for p in r["points"])
        off = r.get("next_page_offset")
        if off is None:
            break
    print(f"order_by walk: total={total_ob} unique={len(seen)} (data={N})")

    # control walk without order_by
    total_pl, off = 0, None
    for _ in range(10):
        body = {"limit": 70, "with_payload": False}
        if off is not None:
            body["offset"] = off
        s, b, _ = safe_request("POST", f"/collections/{C}/points/scroll", json=body)
        if s != 200 or b is None:
            break
        r = b["result"]
        total_pl += len(r["points"])
        off = r.get("next_page_offset")
        if off is None:
            break
    print(f"plain walk: total={total_pl} (data={N})")

    if total_ob < N and total_pl == N:
        print("VERDICT: DEFECT_FOUND — scroll+order_by returns next_page_offset=null "
              f"before exhausting data ({total_ob}/{N} retrievable); pagination cursor lost")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
