# rework2 (EVIDENCE_GAP round 2) for vein_geo_filter_scroll_order_6
# Work order branches:
#   (1) unindexed control: same 4 count requests but collection has NO geo payload
#       index -> if lat=90 returns correct counts (10/40), defect is indexed-path
#       specific (consistent with geohash bit-fold root cause); if also 0, root
#       cause is at the semantic layer (GeoBoundingBox::check_point etc.)
#   (2) scroll ground truth: POST /points/scroll with same geo filters on both
#       unindexed and indexed collections
# Data identical to original script: 50 pts, lon 10+(i%5) in [10,14], lat 40+(i%5)
# in [40,44].
import requests, json, sys, time

BASE_URL = "http://localhost:6333"

def req(method, path, **kwargs):
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    try:
        r = requests.request(method, f"{BASE_URL}{path}", headers=headers, timeout=30, **kwargs)
        try:
            return r.status_code, r.json() if r.text else {}
        except ValueError:
            return r.status_code, {}
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, {}

def setup(name, with_geo_index):
    req("DELETE", f"/collections/{name}")
    s, _ = req("PUT", f"/collections/{name}", json={
        "vectors": {"size": 4, "distance": "Cosine"},
        "optimizer_config": {"indexing_threshold": 1}})
    pts = [{"id": i, "vector": [0.1 * (i % 7), 0.2, 0.3, 1.0],
            "payload": {"loc": {"lon": 10 + (i % 5), "lat": 40 + (i % 5)},
                        "cat": f"c{i % 5}"}} for i in range(1, 51)]
    req("PUT", f"/collections/{name}/points?wait=true", json={"points": pts})
    if with_geo_index:
        req("PUT", f"/collections/{name}/index?wait=true",
            json={"field_name": "loc", "field_schema": "geo"})
        time.sleep(8)
    # confirm index presence/absence from server state
    s, b = req("GET", f"/collections/{name}")
    schema = b.get("result", {}).get("payload_schema", {}) if s == 200 else {"err": s}
    return schema

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

def cnt(name, cond):
    s, b = req("POST", f"/collections/{name}/points/count",
               json={"filter": {"must": [cond]}, "exact": True})
    return s, (b.get("result", {}).get("count") if s == 200 else b)

def scroll_count(name, cond):
    total, offset, pages = 0, None, 0
    while True:
        body = {"filter": {"must": [cond]}, "limit": 100,
                "with_payload": False, "with_vector": False}
        if offset is not None:
            body["offset"] = offset
        s, b = req("POST", f"/collections/{name}/points/scroll", json=body)
        if s != 200:
            return s, f"ERR:{b}"
        pts = b.get("result", {}).get("points", [])
        total += len(pts)
        pages += 1
        offset = b.get("result", {}).get("next_page_offset")
        if offset is None or pages > 10:
            return 200, total

try:
    CU, CI = "vein_r2c6_unidx", "vein_r2c6_idx2"

    print("== (1) UNINDEXED control (no geo payload index) ==")
    sch = setup(CU, with_geo_index=False)
    print(f"[{CU}] payload_schema = {json.dumps(sch, ensure_ascii=False)}")
    for label, cond in [("box_pole", box_pole), ("box_ctl", box_ctl),
                        ("poly_pole", poly_pole), ("poly_ctl", poly_ctl)]:
        s, c = cnt(CU, cond)
        print(f"unindexed count {label}: {s} count={c}")
    print("== (2) scroll ground truth on UNINDEXED ==")
    for label, cond in [("box_pole", box_pole), ("box_ctl", box_ctl),
                        ("poly_pole", poly_pole), ("poly_ctl", poly_ctl)]:
        s, c = scroll_count(CU, cond)
        print(f"unindexed scroll {label}: {s} points={c}")

    print("== (3) INDEXED (geo payload index present) re-run + scroll ==")
    sch = setup(CI, with_geo_index=True)
    print(f"[{CI}] payload_schema = {json.dumps(sch, ensure_ascii=False)}")
    for label, cond in [("box_pole", box_pole), ("box_ctl", box_ctl),
                        ("poly_pole", poly_pole), ("poly_ctl", poly_ctl)]:
        s, c = cnt(CI, cond)
        print(f"indexed count {label}: {s} count={c}")
    print("== (4) scroll on INDEXED ==")
    for label, cond in [("box_pole", box_pole), ("box_ctl", box_ctl),
                        ("poly_pole", poly_pole), ("poly_ctl", poly_ctl)]:
        s, c = scroll_count(CI, cond)
        print(f"indexed scroll {label}: {s} points={c}")
finally:
    for name in (CU, CI):
        try:
            req("DELETE", f"/collections/{name}")
        except Exception:
            pass
