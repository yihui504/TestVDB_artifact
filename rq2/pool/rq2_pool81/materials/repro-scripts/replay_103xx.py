# -*- coding: utf-8 -*-
"""Replay qdrant issue repro steps (10368-10373) from issue transcripts, ported to 6338 (v1.19.0).
Each case: build state per issue steps, send the probe repeatedly, record raw req/resp evidence."""
import json, urllib.request, urllib.error, collections

BASE = "http://127.0.0.1:6338"
LOG = []
def http(m, p, b=None):
    data = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=data, method=m)
    if b: r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            body = resp.read().decode()
            LOG.append(f"=== {m} {p} ===\n{json.dumps(b) if b else ''}\n-> {resp.status} {body}")
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        LOG.append(f"=== {m} {p} ===\n{json.dumps(b) if b else ''}\n-> {e.code} {body}")
        return e.code, json.loads(body) if body else None

def save(n, out):
    open(f"results/rq2_pool81/materials/repro-scripts/replay-{n}.out", "w", encoding="utf-8").write(
        "\n".join(LOG) + "\n\n[STDOUT]\n" + out)

# ---------- 10371: groups without query, nondeterministic members ----------
def case_10371():
    http("DELETE", "/collections/gdemo")
    http("PUT", "/collections/gdemo", {"vectors": {"size": 4, "distance": "Euclid"}})
    pts = [{"id": i, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"grp": "a" if i % 2 else "b"}} for i in range(1, 9)]
    http("PUT", "/collections/gdemo/points?wait=true", {"points": pts})
    sigs = []
    for _ in range(10):
        _, r = http("POST", "/collections/gdemo/points/query/groups",
                    {"group_by": "grp", "limit": 2, "group_size": 3})
        sig = json.dumps([[g["hits"][0].get("payload", {}).get("grp"), [x["id"] for x in g["hits"]]] for g in r["result"]["groups"]])
        sigs.append(sig)
    distinct = len(set(sigs))
    save(10371, f"10 identical requests -> {distinct} distinct member-set signatures\n" + "\n".join(sorted(set(sigs))))
    print(f"10371: {distinct}/10 distinct signatures (issue claims 8)")
    return distinct >= 2

# ---------- 10372: PUT index accepts field_schema as JSON array ----------
def case_10372():
    http("DELETE", "/collections/idxdemo")
    http("PUT", "/collections/idxdemo", {"vectors": {"size": 4, "distance": "Euclid"}})
    pts = [{"id": i, "vector": [float(i)] * 4, "payload": {"tag": f"t{i%3}", "n": i}} for i in range(1, 21)]
    http("PUT", "/collections/idxdemo/points?wait=true", {"points": pts})
    # per issue: field_schema as a JSON array (e.g. ["keyword","text"]-style wrong shape) is accepted instead of 400
    st, r = http("PUT", "/collections/idxdemo/index", {"field_name": "tag", "field_schema": ["keyword"]})
    st2, r2 = http("GET", "/collections/idxdemo")
    schemas = r2["result"]["payload_schema"] if st2 == 200 and "result" in r2 else r2
    save(10372, f"PUT index field_schema=['keyword'] -> {st} {json.dumps(r)}\npayload_schema after: {json.dumps(schemas)}")
    print(f"10372: array field_schema -> HTTP {st} (issue claims accepted, expected 400)")
    return st

# ---------- 10370: PATCH metadata={} does not remove existing metadata ----------
def case_10370():
    http("DELETE", "/collections/meta-demo")
    http("PUT", "/collections/meta-demo", {"vectors": {"size": 4, "distance": "Euclid"},
                                            "metadata": {"owner": "team-a", "env": "test"}})
    st, r = http("PATCH", "/collections/meta-demo", {"metadata": {}})
    st2, r2 = http("GET", "/collections/meta-demo")
    md = r2.get("result", {}).get("metadata") if st2 == 200 else r2
    save(10370, f"PATCH metadata={{}} -> {st} {json.dumps(r)}\nmetadata after: {json.dumps(md)}")
    print(f"10370: metadata after empty patch = {json.dumps(md)} (issue claims old values survive)")
    return md

# ---------- 10369: recommend lookup_from dimension bypass ----------
def case_10369():
    http("DELETE", "/collections/main10369"); http("DELETE", "/collections/lookup10369")
    http("PUT", "/collections/main10369", {"vectors": {"size": 4, "distance": "Euclid"}})
    http("PUT", "/collections/main10369/points?wait=true",
         {"points": [{"id": 1, "vector": [1, 0, 0, 0]}, {"id": 2, "vector": [0, 2, 0, 0]}, {"id": 3, "vector": [1, 1, 0, 0]}]})
    http("PUT", "/collections/lookup10369", {"vectors": {"size": 4, "distance": "Euclid"}})
    http("PUT", "/collections/lookup10369/points?wait=true", {"points": [{"id": 101, "vector": [0.5, 0.5, 0.5, 0.5]}]})
    st0, r0 = http("POST", "/collections/main10369/points/recommend",
                   {"positive": [101], "lookup_from": {"collection": "lookup10369"}, "limit": 3})
    # recreate lookup at size 8
    http("DELETE", "/collections/lookup10369")
    http("PUT", "/collections/lookup10369", {"vectors": {"size": 8, "distance": "Euclid"}})
    http("PUT", "/collections/lookup10369/points?wait=true", {"points": [{"id": 101, "vector": [0.5] * 8}]})
    st1, r1 = http("POST", "/collections/main10369/points/recommend",
                   {"positive": [101], "lookup_from": {"collection": "lookup10369"}, "limit": 3})
    save(10369, f"consistent state -> {st0} {json.dumps(r0)}\nafter lookup recreate at dim 8 -> {st1} {json.dumps(r1)}")
    print(f"10369: consistent={st0}, after-recreate(dim8)={st1} (issue claims 200 with wrong scores)")
    return st0, st1

# ---------- 10368: snapshot recovery priority=replica destroys data ----------
def case_10368():
    http("DELETE", "/collections/snap-demo")
    http("PUT", "/collections/snap-demo", {"vectors": {"size": 4, "distance": "Euclid"}})
    pts = [{"id": i, "vector": [float(i)] * 4} for i in range(1, 6)]
    http("PUT", "/collections/snap-demo/points?wait=true", {"points": pts})
    st, r = http("POST", "/collections/snap-demo/snapshots", {})
    name = (r.get("result") or {}).get("name") if isinstance(r.get("result"), dict) else None
    # delete a live point, then recover with priority=replica (issue: silently destroys newer live data)
    http("POST", "/collections/snap-demo/points/delete?wait=true", {"points": [5]})
    st2, r2 = http("PUT", f"/collections/snap-demo/snapshots/{name}/recover",
                   {"priority": "replica"})
    st3, r3 = http("POST", "/collections/snap-demo/points/count", {"exact": True})
    cnt = r3.get("result", {}).get("count") if isinstance(r3.get("result"), dict) else r3
    save(10368, f"snapshot {name}\ndelete id5 then recover priority=replica -> {st2} {json.dumps(r2)}\ncount after recovery = {json.dumps(cnt)} (issue claims id5 resurrects = silent data destruction)")
    print(f"10368: recover priority=replica -> {st2}; count after = {json.dumps(cnt)}")
    return cnt

# ---------- 10373: scroll on strict-mode collection ignores max_query_limit ----------
def case_10373():
    http("DELETE", "/collections/strict-demo")
    st, r = http("PUT", "/collections/strict-demo",
                 {"vectors": {"size": 4, "distance": "Euclid"},
                  "strict_mode_config": {"max_query_limit": 10, "enabled": True}})
    pts = [{"id": i, "vector": [float(i)] * 4} for i in range(1, 51)]
    http("PUT", "/collections/strict-demo/points?wait=true", {"points": pts})
    st2, r2 = http("POST", "/collections/strict-demo/points/scroll", {"limit": 100})
    got = len((r2.get("result") or {}).get("points", [])) if isinstance(r2.get("result"), dict) else r2
    st3, r3 = http("POST", "/collections/strict-demo/points/scroll", {"limit": 5})
    save(10373, f"create strict(max_query_limit=10) -> {st}\nscroll limit=100 -> {st2}, points returned = {got} (issue claims limit ignored, returns >10)\nscroll limit=5 control -> {st3}")
    print(f"10373: scroll limit=100 under cap 10 -> HTTP {st2}, n={got}")
    return got

if __name__ == "__main__":
    import sys
    only = sys.argv[1] if len(sys.argv) > 1 else None
    cases = {'10371': case_10371, '10372': case_10372, '10370': case_10370,
             '10369': case_10369, '10368': case_10368, '10373': case_10373}
    for k, fn in cases.items():
        if only and k != only:
            continue
        LOG.clear()
        fn()
