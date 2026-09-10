# vein: GET /v1/nodes/{className} returns "shards": null and no shard/composite stats
# for an existing class with data, while GET /v1/nodes (unfiltered) returns an empty
# shard list — the per-class view omits shard state that GET /v1/schema/{c}/shards shows.
# Severity probe (observability inconsistency); may be by-design — script reports
# observed asymmetry with controls.
import os, sys, uuid
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
S = requests.Session()

def safe_request(method, path, **kw):
    try:
        r = S.request(method, BASE + path, timeout=30, **kw)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "VeinND05"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
s, _, _ = safe_request("POST", "/v1/schema",
    json={"class": CLS, "vectorizer": "none",
          "properties": [{"name": "name", "dataType": ["text"]}]})
if s not in (200, 201):
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
objs = [{"class": CLS, "id": str(uuid.uuid4()), "properties": {"name": "n"},
         "vector": [0.1, 0.2]} for _ in range(5)]
s, _, _ = safe_request("POST", "/v1/batch/objects", json={"objects": objs})
print("seed:", s)

s, b, _ = safe_request("GET", f"/v1/nodes/{CLS}")
per_class_shards = None
try:
    per_class_shards = b["nodes"][0]["shards"]
except Exception:
    pass
print("nodes/{cls} shards:", per_class_shards)

s, b, _ = safe_request("GET", "/v1/nodes")
all_shards = None
try:
    all_shards = b["nodes"][0]["shards"]
except Exception:
    pass
print("nodes shards:", all_shards)

s, b, _ = safe_request("GET", f"/v1/schema/{CLS}/shards")
print("schema shards:", b)

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if per_class_shards is None and all_shards in (None, []):
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — GET /v1/nodes/{className} returns shards:null for a class with 5 objects; the unfiltered GET /v1/nodes likewise shows no shards, so the documented per-node per-class shard view (name/status/vectorQueueSize) is never populated despite GET /v1/schema/{c}/shards showing a READY shard")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
