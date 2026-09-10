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
kws = ["red", "blue", "green", "yellow"]
pts = [{"id": i+1, "vector": [1, 0],
        "payload": {"kw": random.choice(kws), "cat": random.choice(["x", "y"])}} for i in range(500)]
http("PUT", "/collections/c/points?wait=true", {"points": pts})
http("PUT", "/collections/c/index", {"field_name": "kw", "field_schema": "keyword"})
http("PUT", "/collections/c/index", {"field_name": "cat", "field_schema": "keyword"})
time.sleep(3)

def count(flt, exact):
    _, r = http("POST", "/collections/c/points/count", {"exact": exact, "filter": flt})
    return r["result"]["count"]

# Single condition (control) — both paths agree:
print("single:", count({"must":[{"key":"kw","match":{"value":"red"}}]}, True),
      count({"must":[{"key":"kw","match":{"value":"red"}}]}, False))   # 130, 130 (OK)

# Same-field compound (true = red, since red excludes blue):
flt = {"must":[{"key":"kw","match":{"value":"red"}}],
       "must_not":[{"key":"kw","match":{"value":"blue"}}]}
print("same-field:", count(flt, True), count(flt, False))  # 130, ~100 (-23%)

# Cross-field compound (independent fields):
flt = {"must":[{"key":"kw","match":{"value":"red"}},
               {"key":"cat","match":{"value":"x"}}]}
print("cross-field:", count(flt, True), count(flt, False))  # 73, ~62 (-14%)
