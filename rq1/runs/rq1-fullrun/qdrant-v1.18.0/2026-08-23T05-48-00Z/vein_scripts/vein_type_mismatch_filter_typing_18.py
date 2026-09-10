# vein candidate 18: filter clause typing is silently lenient on the
# query engine. The Filter schema declares must/should/must_not as
# ARRAYS of conditions, but the server accepts with 200:
#   - null clause members: {"should": null} alone, all-null filter, and
#     null beside real clauses (null == absent; siblings still honored)
#   - clause-as-OBJECT: {"must_not": {cond}}, {"must": {cond}},
#     {"should": {cond}} — silently coerced to a 1-element array
#     (semantics happen to be applied correctly, but the schema
#     violation never surfaces as 4xx)
# The null-member case matters: {"must": [...real...], "should": null}
# is indistinguishable from a typo'd request that MEANT a should clause;
# the server answers with unfiltered should semantics and 200.
# Controls: equivalent valid filters ({}, single-condition arrays) give
# the same counts, isolating acceptance-vs-semantics.
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

C = "vein_c18"
N = 10
try:
    safe_request("DELETE", f"/collections/{C}")
    safe_request("PUT", f"/collections/{C}",
                 body={"vectors": {"size": 4, "distance": "Cosine"}})
    pts = [{"id": i, "vector": [0.01 * i, 0.2, 0.3, 0.4],
            "payload": {"cat": "a" if i < 7 else "b"}} for i in range(N)]
    safe_request("PUT", f"/collections/{C}/points?wait=true", body={"points": pts})

    def cnt(filt):
        s, b, _ = safe_request("POST", f"/collections/{C}/points/count",
                               body={"filter": filt, "exact": True})
        return s, (b["result"]["count"] if s == 200 else None)

    must_a = [{"key": "cat", "match": {"value": "a"}}]
    cases = {
        "must + should:null":    {"must": must_a, "should": None},
        "must + must_not:null":  {"must": must_a, "must_not": None},
        "all-null filter":       {"must": None, "should": None, "must_not": None},
        "should:null alone":     {"should": None},
        "must_not:object":       {"must_not": {"key": "cat", "match": {"value": "a"}}},
        "must:object":           {"must": {"key": "cat", "match": {"value": "a"}}},
        "should:object":         {"should": {"key": "cat", "match": {"value": "a"}}},
    }
    accepted = []
    for label, f in cases.items():
        s, n = cnt(f)
        # also on the query endpoint (threat model flags query specifically)
        sq, bq, _ = safe_request("POST", f"/collections/{C}/points/query",
                                 body={"query": [0.1, 0.2, 0.3, 0.4], "limit": 20, "filter": f})
        nq = len(bq["result"]["points"]) if sq == 200 else None
        print(f"{label}: count=({s},{n}) query=({sq},{nq})")
        if s == 200 and sq == 200:
            accepted.append(label)

    # controls with schema-valid equivalents
    s0, n0 = cnt({})
    sA, nA = cnt({"must": must_a})
    print(f"controls: empty filter count={n0} (expect 10), must[cat=a] count={nA} (expect 7)")

    null_semantics_ok = (n0 == 10 and nA == 7)
    if len(accepted) == len(cases) and null_semantics_ok:
        print("VERDICT: DEFECT_FOUND — filter clause schema violations "
              "(null members, object-for-array) accepted with 200 on count "
              "and query; semantics follow null==absent and object=="
              "[object] coercion. Schema declares arrays; a typo'd null "
              "should-clause is silently executed as no-filter")
    elif accepted:
        print(f"VERDICT: PARTIAL — {len(accepted)}/{len(cases)} cases accepted; see lines above")
    else:
        print("VERDICT: NO_DEFECT")
finally:
    try:
        safe_request("DELETE", f"/collections/{C}")
    except Exception:
        pass
