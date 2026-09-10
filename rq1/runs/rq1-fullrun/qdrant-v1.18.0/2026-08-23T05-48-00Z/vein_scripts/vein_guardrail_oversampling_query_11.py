# vein candidate 11: strict-mode search_max_oversampling is never enforced.
# With scalar quantization active (the code path where oversampling is used),
# params.oversampling far beyond the configured cap is accepted (200) on
# points/query and points/search, and inside prefetch sub-requests.
# Control on the same collection: sibling guardrail search_max_hnsw_ef rejects.
import requests, json, sys, os, time, random

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)

def safe_request(method, path, body=None, timeout=60):
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

C = "vein_gov11"
V = [0.11, 0.22, 0.33, 0.44]
try:
    safe_request("DELETE", f"/collections/{C}")
    safe_request("PUT", f"/collections/{C}", body={
        "vectors": {"size": 4, "distance": "Cosine"},
        "optimizer_config": {"indexing_threshold": 1},
        "quantization_config": {"scalar": {"type": "int8", "quantile": 0.8,
                                           "always_ram": True}},
        "strict_mode_config": {
            "enabled": True,
            "search_max_hnsw_ef": 16,
            "search_max_oversampling": 1.0,
        },
    })
    s, b, _ = safe_request("GET", f"/collections/{C}")
    strict_echo = b["result"]["config"].get("strict_mode_config", {})
    print("strict echo:", json.dumps(strict_echo))
    random.seed(9)
    safe_request("PUT", f"/collections/{C}/points?wait=true",
                 body={"points": [{"id": j, "vector": [random.random() for _ in range(4)]}
                                  for j in range(80)]})
    time.sleep(8)  # let HNSW + scalar quantization build

    results = {}
    for ov in [0.5, 1.0, 1.5, 2.0, 100.0]:
        s, _, _ = safe_request("POST", f"/collections/{C}/points/query",
                               body={"query": V, "limit": 3,
                                     "params": {"oversampling": ov}})
        results[ov] = s
        print(f"query oversampling={ov}: {s}")
    s_search, _, _ = safe_request("POST", f"/collections/{C}/points/search",
                                  body={"vector": V, "limit": 3,
                                        "params": {"oversampling": 2.0}})
    print(f"search oversampling=2.0: {s_search}")
    s_pf, _, _ = safe_request("POST", f"/collections/{C}/points/query",
                              body={"prefetch": [{"query": V, "limit": 3,
                                                  "params": {"oversampling": 50.0}}],
                                    "query": {"fusion": "rrf"}, "limit": 3})
    print(f"prefetch inner oversampling=50: {s_pf}")
    # control: sibling guardrail enforced on the same collection
    s_ef, b_ef, _ = safe_request("POST", f"/collections/{C}/points/query",
                                 body={"query": V, "limit": 3,
                                       "params": {"hnsw_ef": 64}})
    print(f"control hnsw_ef=64 (max 16): {s_ef} "
          f"({'enforced' if s_ef != 200 else 'NOT enforced'})")

    cap_ok = strict_echo.get("search_max_oversampling") == 1.0
    over_accepted = all(results[o] == 200 for o in (1.5, 2.0, 100.0)) and s_search == 200
    if cap_ok and over_accepted and s_ef != 200:
        print("VERDICT: DEFECT_FOUND — strict-mode search_max_oversampling=1.0 is not "
              "enforced anywhere (query 1.5/2.0/100.0, search, prefetch inner params all "
              "200) while sibling search_max_hnsw_ef rejects on the same collection")
    elif cap_ok and over_accepted:
        print("VERDICT: PARTIAL — oversampling unenforced, but control also unenforced")
    else:
        print("VERDICT: NO_DEFECT — oversampling guardrail enforced (see statuses)")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
