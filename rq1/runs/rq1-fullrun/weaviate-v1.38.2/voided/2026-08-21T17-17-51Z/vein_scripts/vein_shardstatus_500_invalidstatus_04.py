# vein: PUT /v1/schema/{className}/shards/{shardName} with an invalid status value
# returns HTTP 500 ("updating db: TYPE_UPDATE_SHARD_STATUS: NOTASTATUS: invalid storage
# status") — a caller-input validation error surfaced as 5xx.
import os, sys
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

CLS = "VeinSH04"
try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass
s, _, _ = safe_request("POST", "/v1/schema",
    json={"class": CLS, "vectorizer": "none",
          "properties": [{"name": "name", "dataType": ["text"]}]})
print("create class:", s)
if s not in (200, 201):
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

s, b, _ = safe_request("GET", f"/v1/schema/{CLS}/shards")
real_shard = b[0]["name"] if s == 200 and b else None
print("real shard:", real_shard)
if not real_shard:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)

s, _, raw = safe_request("PUT", f"/v1/schema/{CLS}/shards/{real_shard}",
                         json={"status": "NOTASTATUS"})
print("invalid status:", s, raw[:140])
invalid_500 = (s == 500 and "invalid storage status" in raw)

# control: valid status on same shard is 200 and takes effect
s, _, raw = safe_request("PUT", f"/v1/schema/{CLS}/shards/{real_shard}",
                         json={"status": "READONLY"})
print("control READONLY:", s)
control_ok = (s == 200)
# restore
safe_request("PUT", f"/v1/schema/{CLS}/shards/{real_shard}", json={"status": "READY"})

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if invalid_500 and control_ok:
    print("VERDICT: DEFECT_FOUND (Type3_ErrorHandling) — invalid shard status value (caller input) returned as HTTP 500 'invalid storage status' instead of a 4xx validation error; control with valid value returns 200")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
