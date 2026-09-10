# vein: PUT /v1/schema/{className}/shards/{shardName} accepts a nonexistent shardName
# with HTTP 200 and echoes the requested status, while the real shard list is unchanged —
# a silent no-op on a management (state-changing) endpoint. Controls:
#  - invalid status value on a REAL shard -> error (500 "invalid storage status") => handler does validate status
#  - nonexistent className -> error ("cannot update shard status to a non-existing index")
# so existence of shardName itself is the unchecked input.
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

CLS = "VeinSH03"
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

# probe: nonexistent shard accepted?
s, b, raw = safe_request("PUT", f"/v1/schema/{CLS}/shards/NoSuchShardXYZ",
                         json={"status": "READONLY"})
print("phantom shard update:", s, raw[:120])
phantom_ok = (s == 200)

# state check: real shards unchanged
s, b, _ = safe_request("GET", f"/v1/schema/{CLS}/shards")
real_status_after = b[0]["status"] if s == 200 and b else None
print("real shard status after phantom update:", real_status_after)

# control 1: invalid status on real shard is rejected
s, _, raw = safe_request("PUT", f"/v1/schema/{CLS}/shards/{real_shard}",
                         json={"status": "NOTASTATUS"})
print("control invalid status:", s, raw[:100])
status_validated = (s >= 400)

# control 2: nonexistent class rejected
s, _, raw = safe_request("PUT", "/v1/schema/NoSuchClassVein/shards/whatever",
                         json={"status": "READONLY"})
print("control nonexistent class:", s, raw[:100])
class_checked = (s >= 400)

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if phantom_ok and real_status_after == "READY" and status_validated and class_checked:
    print("VERDICT: DEFECT_FOUND (Type3_ErrorHandling) — PUT shards/{shardName} on nonexistent shard returns 200 + echoes requested status while performing no state change; the handler validates status value and class existence but not shard existence, so operators get false success for typos in shard names")
    sys.exit(1)
print("VERDICT: NO_DEFECT")
sys.exit(0)
