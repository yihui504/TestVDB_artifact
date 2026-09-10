"""Vein: silently dropped unknown/misplaced schema config keys (state drift).

Discover: unknown keys inside invertedIndexConfig / vectorIndexConfig are
silently dropped without error, and NESTED misplacements are too. E.g.
"indexNullState" set at PROPERTY level (it is a class-level
invertedIndexConfig key, entities/models/inverted_index_config.go:40) is
accepted 200 and dropped from the schema readback. User believes null-state
indexing is on; runtime IsNull filters then fail with
"Nullstate must be indexed to be filterable!".
Source: property parse path keeps only known Property fields
(entities/models/property.go); no strict/unknown-key rejection.

Control: same key at class-level invertedIndexConfig.indexNullState=true is
honored (IsNull filter returns correct count).
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


def main():
    verdict = "NO_DEFECT"
    cls = "VeinSilentDrop"
    try:
        safe_request("DELETE", "/v1/schema/" + cls)
    except Exception:
        pass

    # attack: indexNullState misplaced at property level
    s, _ = safe_request("POST", "/v1/schema", {
        "class": cls,
        "properties": [{"name": "num", "dataType": ["int"],
                        "indexNullState": True}],
    })
    gs, g = safe_request("GET", "/v1/schema/" + cls)
    prop_stored = None
    if g.get("properties"):
        prop_stored = {k: v for k, v in g["properties"][0].items()
                       if k not in ("dataType",)}
    cls_null_state = g.get("invertedIndexConfig", {}).get("indexNullState")
    print("create status=%s property readback=%s class indexNullState=%s" % (
        s, json.dumps(prop_stored), cls_null_state))

    # insert one object with the property present, one with it absent -> null
    safe_request("POST", "/v1/objects", {
        "class": cls, "id": "fffffff1-0000-0000-0000-000000000001",
        "properties": {"num": 7}})
    safe_request("POST", "/v1/objects", {
        "class": cls, "id": "fffffff2-0000-0000-0000-000000000002",
        "properties": {}})
    # runtime IsNull filter: does it work with misplaced key?
    q = ('{ Aggregate { %s(where: {operator: IsNull, path: ["num"], '
         'valueBoolean: true}) { meta { count } } } }') % cls
    fs, fr = safe_request("POST", "/v1/graphql", {"query": q})
    errs = fr.get("errors") or []
    print("IsNull after misplaced key: status=%s errors=%s" % (
        fs, json.dumps(errs)[:100]))

    # control: same key at correct (class) location works
    cls2 = "VeinSilentDropCtl"
    try:
        safe_request("DELETE", "/v1/schema/" + cls2)
    except Exception:
        pass
    safe_request("POST", "/v1/schema", {
        "class": cls2,
        "invertedIndexConfig": {"indexNullState": True},
        "properties": [{"name": "num", "dataType": ["int"]}],
    })
    safe_request("POST", "/v1/objects", {
        "class": cls2, "id": "fffffff3-0000-0000-0000-000000000003",
        "properties": {"num": 7}})
    safe_request("POST", "/v1/objects", {
        "class": cls2, "id": "fffffff4-0000-0000-0000-000000000004",
        "properties": {}})
    q2 = ('{ Aggregate { %s(where: {operator: IsNull, path: ["num"], '
          'valueBoolean: true}) { meta { count } } } }') % cls2
    fs2, fr2 = safe_request("POST", "/v1/graphql", {"query": q2})
    cnt = None
    try:
        cnt = fr2["data"]["Aggregate"][cls2][0]["meta"]["count"]
    except Exception:
        pass
    print("control class-level key IsNull: status=%s count=%s" % (fs2, cnt))

    # DEFECT: create 200 accepted + key silently dropped from property +
    # runtime IsNull fails (GraphQL 200 with errors array), while the same
    # key at class level works.
    if (s == 200 and "indexNullState" not in (prop_stored or {})
            and errs and cnt == 1):
        verdict = "DEFECT_FOUND"

    for c in (cls, cls2):
        try:
            safe_request("DELETE", "/v1/schema/" + c)
        except Exception:
            pass
    print("VERDICT: " + verdict)


if __name__ == "__main__":
    main()
