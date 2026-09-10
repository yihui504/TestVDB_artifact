# vein candidate 6 (round 2): geo_bounding_box / geo_polygon with EXACT pole
# latitude (90.0) in the north boundary silently returns 0 points even though
# matching data exists; 89.9999 returns them all. Indexed geo path only
# (unindexed scan path unaffected). Repro: 50 pts at lat 40-44 / lon 10-14.
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

C = "vein_r2c6"
try:
    safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    pts = [{"id": i, "vector": [0.1 * (i % 7), 0.2, 0.3, 1.0],
            "payload": {"loc": {"lon": 10 + (i % 5), "lat": 40 + (i % 5)},
                        "cat": f"c{i % 5}"}} for i in range(1, 51)]
    safe_request("PUT", f"/collections/{C}/points?wait=true", json={"points": pts})
    safe_request("PUT", f"/collections/{C}/index?wait=true",
                 json={"field_name": "loc", "field_schema": "geo"})
    time.sleep(8)

    def cnt(cond):
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               json={"filter": {"must": [cond]}, "exact": True})
        return (s, b["result"]["count"] if s == 200 else b)

    box_pole = {"key": "loc", "geo_bounding_box": {
        "top_left": {"lon": 10, "lat": 90}, "bottom_right": {"lon": 12, "lat": -50}}}
    box_ctl = {"key": "loc", "geo_bounding_box": {
        "top_left": {"lon": 10, "lat": 89.9999}, "bottom_right": {"lon": 12, "lat": -50}}}
    poly_pole = {"key": "loc", "geo_polygon": {"exterior": {"points": [
        {"lon": 8, "lat": 90}, {"lon": 14, "lat": 90},
        {"lon": 14, "lat": -50}, {"lon": 8, "lat": -50}, {"lon": 8, "lat": 90}]}}}
    poly_ctl = {"key": "loc", "geo_polygon": {"exterior": {"points": [
        {"lon": 8, "lat": 89.9999}, {"lon": 14, "lat": 89.9999},
        {"lon": 14, "lat": -50}, {"lon": 8, "lat": -50}, {"lon": 8, "lat": 89.9999}]}}}

    sp, cp = cnt(box_pole); sc, cc = cnt(box_ctl)
    print(f"bbox top lat=90.0: {sp} count={cp}")
    print(f"bbox top lat=89.9999 (control): {sc} count={cc}")
    pp, pc = cnt(poly_pole); pc2, cc2 = cnt(poly_ctl)
    print(f"polygon pole vertex lat=90.0: {pp} count={pc}")
    print(f"polygon pole vertex 89.9999 (control): {pc2} count={cc2}")

    ok_ctl = (sc == 200 and cc > 0 and pc2 == 200 and cc2 > 0)
    bug = (cp == 0 and pc == 0)
    if ok_ctl and bug:
        print("VERDICT: DEFECT_FOUND — geo bbox/polygon with exact north-pole "
              "latitude 90.0 (valid input) returns 0; 89.9999 returns all matches")
    elif not ok_ctl:
        print("VERDICT: NO_DEFECT — control groups did not establish baseline")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
