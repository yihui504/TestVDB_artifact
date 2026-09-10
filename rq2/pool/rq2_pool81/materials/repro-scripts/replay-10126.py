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
pts = [{"id": i+1, "vector": [1, 0],
        "payload": {"loc": {"lat": random.uniform(-89, 89), "lon": random.uniform(-179, 179)}}}
       for i in range(1000)]
http("PUT", "/collections/c/points?wait=true", {"points": pts})
http("PUT", "/collections/c/index", {"field_name": "loc", "field_schema": "geo"})
time.sleep(3)

def count(flt, exact):
    _, r = http("POST", "/collections/c/points/count", {"exact": exact, "filter": flt})
    return r["result"]["count"]

def radius(r):
    flt = {"must":[{"key":"loc","geo_radius":{"center":{"lat":0,"lon":0},"radius":r}}]}
    return count(flt, True), count(flt, False)

for r in [500_000, 2_000_000, 5_000_000, 10_000_000, 20_000_000]:
    t, f = radius(r)
    err = (f - t) * 100 // t if t else 0
    print(f"radius={r//1000}km: exact={t:4d} approx={f:4d} ({err:+d}%)")
