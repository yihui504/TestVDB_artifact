"""Vein: hnsw dynamicEfMin > dynamicEfMax cross-parameter validation missing.

Discover: POST /v1/schema with vectorIndexConfig dynamicEfMin=500 > dynamicEfMax=100
is accepted with 200 and persisted verbatim. Source:
.weaviate-src-1381/entities/vectorindex/hnsw/config.go:260 validate() checks
maxConnections/efConstruction/filterStrategy but never DynamicEFMin/Max
(parsed unchecked at lines 183-195). DefaultDynamicEFMin=100, DefaultDynamicEFMax=500.

Control groups:
  1. efConstruction=1 (single-field, validated) -> 422
  2. maxConnections=1 (single-field, validated) -> 422
Cross-field inversion and negatives are silently stored.
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
    for cls in ("VeinSchemaEf", "VeinSchemaEfCtl1", "VeinSchemaEfCtl2"):
        try:
            safe_request("DELETE", "/v1/schema/" + cls)
        except Exception:
            pass

    # attack: inverted cross relationship
    s, r = safe_request("POST", "/v1/schema", {
        "class": "VeinSchemaEf",
        "vectorIndexConfig": {"dynamicEfMin": 500, "dynamicEfMax": 100},
    })
    stored_min = stored_max = None
    if s == 200:
        gs, g = safe_request("GET", "/v1/schema/VeinSchemaEf")
        cfg = g.get("vectorIndexConfig", {})
        stored_min, stored_max = cfg.get("dynamicEfMin"), cfg.get("dynamicEfMax")
    print("attack efMin>efMax: status=%s stored min=%s max=%s" % (s, stored_min, stored_max))

    # control 1: validated single field
    s1, r1 = safe_request("POST", "/v1/schema", {
        "class": "VeinSchemaEfCtl1",
        "vectorIndexConfig": {"efConstruction": 1},
    })
    print("control efConstruction=1: status=%s err=%s" % (
        s1, json.dumps(r1)[:120]))

    # control 2: validated single field
    s2, r2 = safe_request("POST", "/v1/schema", {
        "class": "VeinSchemaEfCtl2",
        "vectorIndexConfig": {"maxConnections": 1},
    })
    print("control maxConnections=1: status=%s err=%s" % (
        s2, json.dumps(r2)[:120]))

    if s == 200 and stored_min == 500 and stored_max == 100 and s1 == 422 and s2 == 422:
        verdict = "DEFECT_FOUND"

    # cleanup
    for cls in ("VeinSchemaEf", "VeinSchemaEfCtl1", "VeinSchemaEfCtl2"):
        try:
            safe_request("DELETE", "/v1/schema/" + cls)
        except Exception:
            pass

    print("VERDICT: " + verdict)


if __name__ == "__main__":
    main()
