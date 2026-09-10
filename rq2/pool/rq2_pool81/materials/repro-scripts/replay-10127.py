import json, urllib.request, random, time

BASE = "http://127.0.0.1:6337"

def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, json.loads(resp.read().decode())

http("DELETE", "/collections/c")
http("PUT", "/collections/c", {
    "vectors": {"size": 2, "distance": "Cosine"},
    "optimizer_config": {"indexing_threshold": 1}
})
random.seed(42)
kws = ["red", "blue", "green", "yellow", "purple"]
pts = [{"id": i+1, "vector": [1, 0], "payload": {"kw": random.choice(kws)}} for i in range(500)]
http("PUT", "/collections/c/points?wait=true", {"points": pts})
http("PUT", "/collections/c/index", {"field_name": "kw", "field_schema": "keyword"})
time.sleep(3)

def count(flt, exact):
    _, r = http("POST", "/collections/c/points/count", {"exact": exact, "filter": flt})
    return r["result"]["count"]

def any_of(vals):
    flt = {"must":[{"key":"kw","match":{"any":vals}}]}
    return count(flt, True), count(flt, False)

for n in range(1, 6):
    vals = kws[:n]
    t, f = any_of(vals)
    err = (f - t) * 100 // t if t else 0
    print(f"match_any {n} values {vals}: exact={t:3d} approx={f:3d} ({err:+d}%)")
