#!/usr/bin/env python3
"""MRE for TESTVDB-QDRANT-2 (vein_geo_filter_scroll_order_6): geo filter with
exact pole latitude +90 silently returns 0 results on the indexed path
(geohash bit-collapse).

Defect: lat=90.0 is a valid input (GeoPoint::validate accepts the closed
interval [-90, 90]). But when a geo payload index exists, a bounding box or
polygon whose north boundary is exactly 90.0 returns count=0 / scroll=0 —
the geohash encoder assumes open-interval normalization, bits collapse, and
the candidate grid covers no data. The unindexed path and the 89.9999
control return the correct results (10 / 40).

Source: defects/defect-2.md; log output_vein_geo_filter_scroll_order_6.log
(indexed/unindexed divergence additionally confirmed by rework2 log).
"""
import os, sys, json, time
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:6333")
HEADERS = {"Content-Type": "application/json"}

C_IDX = "mre_q2_geo_idx"    # with geo payload index
C_UNIDX = "mre_q2_geo_unidx"  # without geo payload index (ground truth)


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


def setup(coll, create_index):
    safe_request("DELETE", f"/collections/{coll}")
    st, _ = safe_request("PUT", f"/collections/{coll}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    if st not in (200, 201):
        return False
    pts = [{"id": i, "vector": [0.1 * (i % 7), 0.2, 0.3, 1.0],
            "payload": {"loc": {"lon": 10 + (i % 5), "lat": 40 + (i % 5)},
                        "cat": f"c{i % 5}"}} for i in range(1, 51)]
    safe_request("PUT", f"/collections/{coll}/points?wait=true", json={"points": pts})
    if create_index:
        safe_request("PUT", f"/collections/{coll}/index?wait=true",
                     json={"field_name": "loc", "field_schema": "geo"})
        time.sleep(8)
    return True


def geo_count(coll, cond):
    st, body = safe_request("POST", f"/collections/{coll}/points/count",
                            json={"filter": {"must": [cond]}, "exact": True})
    n = None
    if st == 200 and isinstance(body, dict) and isinstance(body.get("result"), dict):
        n = body["result"].get("count")
    return st, n


def reproduce():
    # Step 1: setup - twin collections, one geo-indexed, one not
    if not setup(C_IDX, create_index=True):
        print("setup failed (indexed collection)")
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False
    if not setup(C_UNIDX, create_index=False):
        print("setup failed (unindexed collection)")
        print("\nVERDICT: NOT_REPRODUCED (setup failed)")
        return False

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

    # Step 2: trigger - pole-latitude queries on both collections
    s_ip, c_ip = geo_count(C_IDX, box_pole)      # indexed, lat=90.0
    s_ic, c_ic = geo_count(C_IDX, box_ctl)       # indexed control 89.9999
    s_up, c_up = geo_count(C_UNIDX, box_pole)    # unindexed ground truth

    s_pp, c_pp = geo_count(C_IDX, poly_pole)
    s_pc, c_pc = geo_count(C_IDX, poly_ctl)
    s_upp, c_upp = geo_count(C_UNIDX, poly_pole)

    # Step 3: verify
    print(f"indexed   bbox top lat=90.0:      {s_ip} count={c_ip}")
    print(f"unindexed bbox top lat=90.0 (GT):  {s_up} count={c_up}")
    print(f"indexed   bbox 89.9999 (control):  {s_ic} count={c_ic}")
    print(f"indexed   polygon pole lat=90.0:   {s_pp} count={c_pp}")
    print(f"unindexed polygon pole (GT):       {s_upp} count={c_upp}")
    print(f"indexed   polygon 89.9999 (ctl):   {s_pc} count={c_pc}")

    baseline_ok = (s_ic == 200 and c_ic and c_ic > 0
                   and s_pc == 200 and c_pc and c_pc > 0
                   and c_up == c_ic and c_upp == c_pc)
    pole_zero = (s_ip == 200 and c_ip == 0 and s_pp == 200 and c_pp == 0)
    if baseline_ok and pole_zero:
        print("\nVERDICT: DEFECT_REPRODUCED")
        return True
    if not baseline_ok:
        print("\nVERDICT: NOT_REPRODUCED (controls did not establish baseline)")
        return False
    print("\nVERDICT: NOT_REPRODUCED (pole-latitude queries returned non-zero)")
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if reproduce() else 1)
    finally:
        safe_request("DELETE", f"/collections/{C_IDX}")
        safe_request("DELETE", f"/collections/{C_UNIDX}")
