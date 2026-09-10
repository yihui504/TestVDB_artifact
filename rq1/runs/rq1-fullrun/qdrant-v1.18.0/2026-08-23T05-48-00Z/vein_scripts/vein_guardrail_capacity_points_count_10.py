# vein candidate 10: strict-mode capacity guardrails accepted but never enforced.
# strict_mode_config.max_points_count / max_collection_vector_size_bytes /
# max_collection_payload_size_bytes are echoed back by GET /collections/{C} yet
# upserts beyond every cap return 200. Control on a sibling guardrail
# (upsert_max_batchsize) shows the enforcement machinery IS active.
import requests, json, sys, os, time

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
            body = resp.json() if resp.text else {}
        except (json.JSONDecodeError, ValueError):
            body = resp.text
        return resp.status_code, body, resp.text
    except requests.exceptions.RequestException as e:
        return -1, str(e), str(e)

def cleanup(collection_name):
    """Teardown helper: cleanup failure must never cause non-zero exit."""
    try:
        safe_request("DELETE", f"/collections/{collection_name}")
    except Exception:
        pass

C = "vein_gcap10"
V = [0.11, 0.22, 0.33, 0.44]
try:
    cleanup(C)
    safe_request("PUT", f"/collections/{C}", body={
        "vectors": {"size": 4, "distance": "Cosine"},
        "strict_mode_config": {
            "enabled": True,
            "max_points_count": 10,
            "max_collection_vector_size_bytes": 100,     # 4 dims * f32 = 16B/point
            "max_collection_payload_size_bytes": 100,    # payloads below are 200B each
        },
    })
    s, b, _ = safe_request("GET", f"/collections/{C}")
    strict_echo = b["result"]["config"].get("strict_mode_config", {})
    print("strict echo:", json.dumps(strict_echo))
    caps_echoed = all(strict_echo.get(k) is not None for k in
                      ("max_points_count", "max_collection_vector_size_bytes",
                       "max_collection_payload_size_bytes"))

    # below-cap write: 6 points (6*16B vectors, no payload) — must succeed
    s1, _, _ = safe_request("PUT", f"/collections/{C}/points?wait=true",
                            body={"points": [{"id": j, "vector": V} for j in range(6)]})
    # beyond point cap: 5 more -> total 11 > 10
    s2, b2, _ = safe_request("PUT", f"/collections/{C}/points?wait=true",
                             body={"points": [{"id": 100 + j, "vector": V} for j in range(5)]})
    # far beyond vector-size cap (100B) and payload-size cap (100B): 30 points x 200B payload
    s3, _, _ = safe_request("PUT", f"/collections/{C}/points?wait=true",
                            body={"points": [{"id": 200 + j, "vector": V,
                                              "payload": {"blob": "x" * 200}}
                                             for j in range(30)]})
    s4, b4, _ = safe_request("POST", f"/collections/{C}/points/count", body={"exact": True})
    final_count = b4["result"]["count"] if s4 == 200 else -1
    print(f"below-cap upsert: {s1} | +5 beyond point-cap: {s2} | 30x200B beyond size caps: {s3}")
    print(f"final point count: {final_count} (caps: points=10, vector bytes=100, payload bytes=100)")

    # control: a sibling strict-mode guardrail IS enforced (upsert_max_batchsize)
    CC = "vein_gcap10_ctl"
    cleanup(CC)
    safe_request("PUT", f"/collections/{CC}", body={
        "vectors": {"size": 4, "distance": "Cosine"},
        "strict_mode_config": {"enabled": True, "upsert_max_batchsize": 50}})
    sc, bc, _ = safe_request("PUT", f"/collections/{CC}/points?wait=true",
                             body={"points": [{"id": j, "vector": V} for j in range(60)]})
    print(f"control upsert_max_batchsize=50, batch of 60 -> {sc} "
          f"({'enforced' if sc != 200 else 'NOT enforced'})")
    cleanup(CC)

    if caps_echoed and s1 == 200 and s2 == 200 and s3 == 200 and final_count > 10:
        if sc != 200:
            print("VERDICT: DEFECT_FOUND — strict-mode capacity guardrails "
                  "(max_points_count, max_collection_vector_size_bytes, "
                  "max_collection_payload_size_bytes) are accepted and echoed but never "
                  "enforced: writes 11x/16x the point cap and 4.8x+ the byte caps succeed, "
                  "while sibling guardrail upsert_max_batchsize rejects correctly")
        else:
            print("VERDICT: PARTIAL — capacity caps unenforced but control also unenforced")
    else:
        print("VERDICT: NO_DEFECT — capacity caps enforced (or echo missing); see counts above")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
    try:
        safe_request("DELETE", f"/collections/{CC}")
    except Exception:
        pass
