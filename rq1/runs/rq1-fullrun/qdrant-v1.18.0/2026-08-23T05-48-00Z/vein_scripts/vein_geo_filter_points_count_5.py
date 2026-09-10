# vein candidate 5: count(exact:false) for geo filters diverges from exact and
# scroll (bbox antimeridian truth 13 -> approx 50; geo_radius truth 26 -> approx 200).
# The geo cardinality estimator appears to approximate whole-hemisphere coverage
# regardless of the actual bounding box / radius shape.
import requests, json, sys, os, time, random

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

C = "vein_c5"
N = 200
try:
    safe_request("PUT", f"/collections/{C}",
        json={"vectors": {"size": 4, "distance": "Cosine"},
              "optimizer_config": {"indexing_threshold": 1}})
    random.seed(11)
    for i in range(0, N, 100):
        batch = [{"id": j, "vector": [random.random() for _ in range(4)],
                  "payload": {"geo": {"lon": random.uniform(-179, 179),
                                      "lat": random.uniform(-80, 80)}}}
                 for j in range(i, min(i + 100, N))]
        safe_request("PUT", f"/collections/{C}/points?wait=true", json={"points": batch})
    safe_request("PUT", f"/collections/{C}/index?wait=true",
                 json={"field_name": "geo", "field_schema": "geo"})
    time.sleep(8)

    def count(exact, cond):
        flt = {"must": [cond]}
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               json={"filter": flt, "exact": exact})
        return b["result"]["count"] if s == 200 else None

    def scroll_count(cond):
        flt = {"must": [cond]}
        n, off = 0, None
        while True:
            body = {"filter": flt, "limit": 100, "with_payload": False}
            if off is not None:
                body["offset"] = off
            s, b, _ = safe_request("POST", f"/collections/{C}/points/scroll", json=body)
            if s != 200 or b is None:
                return None
            n += len(b["result"]["points"])
            off = b["result"].get("next_page_offset")
            if off is None or n > 5000:
                return n

    bbox = {"key": "geo", "geo_bounding_box": {
        "top_left": {"lon": 170, "lat": 80}, "bottom_right": {"lon": -170, "lat": -80}}}
    radius = {"key": "geo", "geo_radius": {
        "center": {"lon": 0, "lat": 0}, "radius": 6.4e6}}
    for name, cond in [("bbox antimeridian", bbox), ("radius earth", radius)]:
        e, a, sc = count(True, cond), count(False, cond), scroll_count(cond)
        print(f"{name}: exact={e} approx={a} scroll={sc}")
        if None not in (e, a, sc):
            print(f"  approx deviation from truth: {a - sc} ({100 * abs(a - sc) / max(sc, 1):.0f}%)")
    e, a = count(True, bbox), count(False, bbox)
    er, ar = count(True, radius), count(False, radius)
    tol = lambda est, ex: abs(est - ex) <= max(2, 0.2 * ex)
    if None not in (e, a, er, ar) and (not tol(a, e) or not tol(ar, er)):
        print("VERDICT: DEFECT_FOUND — geo filter approximate cardinality diverges "
              "far beyond tolerance from exact path and scroll ground truth")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
