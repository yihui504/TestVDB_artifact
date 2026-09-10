# vein candidate 9: score_threshold uses strict '>' — points whose score EQUALS
# the threshold are silently dropped. Docs describe the option as "cut off results
# with less than a threshold", i.e. equal scores must be kept.
# Systemic across the query family: points/search, points/query,
# points/query+groups, points/recommend (server-reported top score fed back as
# threshold excludes the top point on every endpoint).
import requests, json, sys, os, random, time

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

C = "vein_th9"
N = 20
V = [0.11, 0.22, 0.33, 0.44]
try:
    safe_request("DELETE", f"/collections/{C}")
    safe_request("PUT", f"/collections/{C}",
                 body={"vectors": {"size": 4, "distance": "Cosine"}})
    random.seed(5)
    pts = [{"id": j, "vector": [random.random() for _ in range(4)]} for j in range(N)]
    # one point with a vector EXACTLY equal to the query vector -> top score is
    # the server-computed similarity of an identical vector (no rounding assumptions)
    pts[3]["vector"] = list(V)
    safe_request("PUT", f"/collections/{C}/points?wait=true", body={"points": pts})
    time.sleep(2)

    def scores(method, path, body):
        s, b, _ = safe_request(method, path, body=body)
        if s != 200:
            return s, None
        return s, b["result"]

    # search: capture the server-reported top score S, then feed S back as threshold
    s, res = scores("POST", f"/collections/{C}/points/search", {"vector": V, "limit": 3})
    top_score = res[0]["score"]
    print(f"search top score S={top_score!r} id={res[0]['id']}")
    _, kept_eq = scores("POST", f"/collections/{C}/points/search",
                        {"vector": V, "limit": 5, "score_threshold": top_score})
    _, kept_lo = scores("POST", f"/collections/{C}/points/search",
                        {"vector": V, "limit": 5, "score_threshold": top_score - 0.01})
    print(f"search th==S: n={len(kept_eq)} | th==S-0.01: n={len(kept_lo)}")

    # query API
    s, res = scores("POST", f"/collections/{C}/points/query", {"query": V, "limit": 3})
    q_top = res["points"][0]["score"]
    _, q_eq = scores("POST", f"/collections/{C}/points/query",
                     {"query": V, "limit": 5, "score_threshold": q_top})
    print(f"query  th==S: n={len(q_eq['points'])}")

    # recommend (query point id 3 whose vector == V)
    s, res = scores("POST", f"/collections/{C}/points/recommend",
                    {"positive": [3], "limit": 3})
    r_top = res[0]["score"]
    _, r_eq = scores("POST", f"/collections/{C}/points/recommend",
                     {"positive": [3], "limit": 5, "score_threshold": r_top})
    print(f"recommend th==S: n={len(r_eq)}")

    # query+groups (two groups so group count itself can drop)
    safe_request("POST", f"/collections/{C}/points/payload?wait=true",
                 body={"payload": {"cat": "a"}, "points": [j for j in range(N) if j % 2]})
    safe_request("POST", f"/collections/{C}/points/payload?wait=true",
                 body={"payload": {"cat": "b"}, "points": [j for j in range(N) if not j % 2]})
    s, res = scores("POST", f"/collections/{C}/points/query/groups",
                    {"query": V, "group_by": "cat", "group_size": 3, "limit": 2})
    g_top = res["groups"][0]["hits"][0]["score"]
    s2, g_res = scores("POST", f"/collections/{C}/points/query/groups",
                       {"query": V, "group_by": "cat", "group_size": 3, "limit": 2,
                        "score_threshold": g_top})
    n_groups_eq = len(g_res["groups"]) if s2 == 200 else -1
    s3, g_lo = scores("POST", f"/collections/{C}/points/query/groups",
                      {"query": V, "group_by": "cat", "group_size": 3, "limit": 2,
                       "score_threshold": g_top - 0.01})
    n_groups_lo = len(g_lo["groups"]) if s3 == 200 else -1
    print(f"groups  th==S: n={n_groups_eq} | th==S-0.01: n={n_groups_lo}")

    dropped = (len(kept_eq) == 0 and len(kept_lo) > 0)
    if dropped and len(q_eq["points"]) == 0 and len(r_eq) == 0 and n_groups_eq == 0:
        print("VERDICT: DEFECT_FOUND — score_threshold excludes points whose score "
              "EQUALS the threshold (strict >) on search/query/recommend/groups; "
              "docs say 'cut off results with less than a threshold' (equal must stay)")
    elif dropped:
        print("VERDICT: PARTIAL — equality drop confirmed on search; see per-endpoint counts above")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
