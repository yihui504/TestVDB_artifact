# vein candidate 16: collection creation accepts vectors={} (empty map)
# and even a request with the vectors field MISSING entirely — both
# return 200 and create a green collection that can never hold data:
# every upsert and every vector query fail with 400
# "Not existing vector name error: " (note the EMPTY vector name), and
# PATCH cannot rescue it because VectorsConfigDiff has no size field
# (the diff schema rejects {"size":4,...}). Result: a permanently
# unusable collection created with 200 OK.
# Control: normal creation accepts upserts and queries on the same server.
import requests, json, sys, os

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, path, body=None, timeout=30):
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.request(method, url, json=body,
                                headers={"Content-Type": "application/json"},
                                timeout=timeout)
        try:
            jbody = resp.json() if resp.text else {}
        except (json.JSONDecodeError, ValueError):
            jbody = resp.text
        return resp.status_code, jbody, resp.text
    except requests.exceptions.RequestException as e:
        return -1, str(e), str(e)

try:
    for name, create_body, label in [
        ("vein_c16a", {"vectors": {}}, "vectors={} (empty map)"),
        ("vein_c16b", {"shard_number": 1}, "vectors field missing"),
    ]:
        safe_request("DELETE", f"/collections/{name}")
        s, b, _ = safe_request("PUT", f"/collections/{name}", body=create_body)
        print(f"[{label}] create: {s}")
        created = (s == 200)
        up_s, up_b, _ = safe_request(
            "PUT", f"/collections/{name}/points?wait=true",
            body={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
        q_s, q_b, _ = safe_request(
            "POST", f"/collections/{name}/points/query",
            body={"query": [0.1, 0.2, 0.3, 0.4], "limit": 3})
        p_s, p_b, _ = safe_request(
            "PATCH", f"/collections/{name}",
            body={"vectors": {"size": 4, "distance": "Cosine"}})
        err = ""
        if up_s == 200:
            err = up_b["result"].get("error", "") if isinstance(up_b, dict) else ""
        print(f"  upsert={up_s} query={q_s} patch-rescue={p_s}"
              + (f" upsert_err={str(up_b)[:80]}" if up_s != 200 else ""))
        if created and up_s != 200 and q_s != 200 and p_s != 200:
            print(f"  -> unusable collection alive: created 200, all writes/reads "
                  f"rejected, no PATCH rescue ({label})")
        globals()[f"ok_{name}"] = created and up_s != 200 and q_s != 200 and p_s != 200
        safe_request("DELETE", f"/collections/{name}")

    # control: normal collection on the same server works end-to-end
    safe_request("DELETE", "/collections/vein_c16ctl")
    safe_request("PUT", "/collections/vein_c16ctl",
                 body={"vectors": {"size": 4, "distance": "Cosine"}})
    s, _, _ = safe_request("PUT", "/collections/vein_c16ctl/points?wait=true",
                           body={"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
    print(f"[control normal create] upsert={s} (expect 200)")

    if ok_vein_c16a and ok_vein_c16b and s == 200:
        print("VERDICT: DEFECT_FOUND — PUT /collections/{name} accepts "
              "vectors={} and a missing vectors field (200), creating green "
              "collections that reject every upsert/query with 400 "
              "'Not existing vector name error: ' and cannot be repaired via "
              "PATCH (diff schema has no size field)")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    for name in ("vein_c16a", "vein_c16b", "vein_c16ctl"):
        try:
            safe_request("DELETE", f"/collections/{name}")
        except Exception:
            pass
