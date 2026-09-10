import json, urllib.request, time

BASE = "http://127.0.0.1:6337"

def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode())

def run(size):
    http("DELETE", "/collections/c")
    http("PUT", "/collections/c", {
        "vectors": {"size": 2, "distance": "Cosine"},
        "optimizer_config": {"indexing_threshold": 1}
    })
    # 80% of points carry "kw": "red", 20% are MISSING kw
    # is_empty should match the 20% missing kw
    pts = []
    for i in range(size):
        p = {"id": i + 1, "vector": [1, 0]}
        if i % 5 != 0:
            p["payload"] = {"kw": "red"}
        pts.append(p)
    http("PUT", "/collections/c/points?wait=true", {"points": pts})
    http("PUT", "/collections/c/index", {"field_name": "kw", "field_schema": "keyword"})
    time.sleep(3)

    def count(flt, exact):
        _, r = http("POST", "/collections/c/points/count", {
            "exact": exact,
            "filter": {"must": [flt]}
        })
        return r["result"]["count"]

    ie_true  = count({"is_empty": {"key": "kw"}}, True)
    ie_false = count({"is_empty": {"key": "kw"}}, False)
    in_true  = count({"is_null": {"key": "kw"}}, True)
    in_false = count({"is_null": {"key": "kw"}}, False)
    err = (ie_false - ie_true) * 100 // ie_true if ie_true else 0
    print(f"size={size}: is_empty exact={ie_true} approx={ie_false} ({err}%) | "
          f"is_null exact={in_true} approx={in_false}")

run(200)
run(500)
run(1000)
