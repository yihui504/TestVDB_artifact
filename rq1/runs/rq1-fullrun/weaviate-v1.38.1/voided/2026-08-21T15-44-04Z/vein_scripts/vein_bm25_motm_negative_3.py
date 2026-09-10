"""Vein: bm25 searchOperator.minimumOrTokensMatch accepts negative and
out-of-range values without validation, silently misbehaving.

Discover: minimumOrTokensMatch=-5 is accepted (200) and behaves as
"no threshold" (equivalent to unset); the value has no declared negative
semantics. Source: parsed unchecked at
.weaviate-src-1381/adapters/handlers/graphql/local/common_filters/bm25.go:86,
consumed at adapters/repos/db/inverted/bm25_searcher.go:379 where only
operator==And forces len(queryTerms); negative values flow into
DoWand gating (adapters/repos/db/lsmkv/search_segment.go:146
termsMatched >= minimumOrTokensMatch).

Control: motm=1 behaves like unset; motm>=3 on 3-token query equals AND.
Defect shape: silent acceptance of meaningless negative parameter with
unvalidated API surface (contrast: where-filters DO validate value types).
"""
import json
import urllib.request

BASE = "http://localhost:8080"


def safe_request(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"raw": raw}


def gql(query):
    s, r = safe_request("POST", "/v1/graphql", {"query": query})
    return s, r


def main():
    verdict = "NO_DEFECT"
    cls = "VeinMotm"
    try:
        safe_request("DELETE", "/v1/schema/" + cls)
    except Exception:
        pass
    s, _ = safe_request("POST", "/v1/schema", {
        "class": cls,
        "properties": [{"name": "text", "dataType": ["text"]}],
    })
    assert s == 200
    s, _ = safe_request("POST", "/v1/batch/objects", {"objects": [
        {"class": cls, "id": "eeeeeee1-0000-0000-0000-000000000001",
         "properties": {"text": "apple banana"}},
        {"class": cls, "id": "eeeeeee2-0000-0000-0000-000000000002",
         "properties": {"text": "apple cherry"}},
        {"class": cls, "id": "eeeeeee3-0000-0000-0000-000000000003",
         "properties": {"text": "banana cherry"}},
        {"class": cls, "id": "eeeeeee4-0000-0000-0000-000000000004",
         "properties": {"text": "apple"}},
        {"class": cls, "id": "eeeeeee5-0000-0000-0000-000000000005",
         "properties": {"text": "cherry"}},
    ]})
    assert s == 200

    def run(motm):
        q = ('{ Get { %s(bm25: {query: "apple banana cherry", '
             'properties: ["text"], searchOperator: {operator: Or, '
             'minimumOrTokensMatch: %d}}) { text } } }') % (cls, motm)
        s, r = gql(q)
        got = r.get("data", {}).get("Get", {}).get(cls)
        return s, got, json.dumps(r.get("errors", []))[:120]

    s0, unset, _ = run(0)
    sneg, neg, _ = run(-5)
    s1, one, _ = run(1)
    print("unset(0)=%s | negative(-5)=%s | 1=%s" % (unset, neg, one))

    # negative accepted as valid request and equals no-threshold behavior
    if sneg == 200 and neg is not None and len(neg) == 5:
        verdict = "DEFECT_FOUND"

    try:
        safe_request("DELETE", "/v1/schema/" + cls)
    except Exception:
        pass
    print("VERDICT: " + verdict)


if __name__ == "__main__":
    main()
