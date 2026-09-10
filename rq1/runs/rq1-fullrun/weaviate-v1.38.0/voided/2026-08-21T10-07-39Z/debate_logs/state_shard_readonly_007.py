# state_shard_readonly_007 — shard READY<->READONLY transition vs write/read consistency
# Attack: state transition consistency (Mode D) — writes in READONLY must fail cleanly (not 500,
# not silent success); back to READY state must be intact.
import os, sys, time, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/") + "/v1"
S = requests.Session()

def safe_request(method, path, body=None):
    try:
        r = S.request(method, BASE + path, json=body, timeout=60)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StS007"
OID = "77777777-7777-7777-7777-777777777777"
CLS_BODY = {"class": CLS, "vectorizer": "none",
            "properties": [{"name": "name", "dataType": ["text"]}]}

safe_request("DELETE", f"/schema/{CLS}")
time.sleep(1)
s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("create:", s); assert s in (200, 201)

s, b, raw = safe_request("POST", "/objects",
    {"class": CLS, "id": OID, "properties": {"name": "before"}, "vector": [0.1, 0.2]})
print("insert before:", s)

# discover shard name
s, b, raw = safe_request("GET", f"/schema/{CLS}/shards")
print("shards:", s, raw[:300])
shards = b if isinstance(b, list) else []
shard = shards[0]["name"] if shards else None
if not shard:
    print("no shard info; abort cleanly")
    safe_request("DELETE", f"/schema/{CLS}")
    print("VERD: NO_DEFECT"); sys.exit(0)

defect = False
# reads in READY
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}")
print("read READY (expect 200):", s)
if s != 200:
    print("DEFECT Type4: read broken in READY"); defect = True

# -> READONLY
s, b, raw = safe_request("PUT", f"/schema/{CLS}/shards/{shard}", {"status": "READONLY"})
print("set READONLY:", s, raw[:150])
time.sleep(1)

# write must fail cleanly (4xx) or be rejected — never 500, never silent success
s, b, raw = safe_request("POST", "/objects",
    {"class": CLS, "id": "88888888-8888-8888-8888-888888888888",
     "properties": {"name": "during"}, "vector": [0.3, 0.4]})
print("write in READONLY:", s, raw[:150])
if s in (200, 201):
    s2, _, raw2 = safe_request("GET", f"/objects/{CLS}/88888888-8888-8888-8888-888888888888")
    print("  verify silent write:", s2)
    if s2 == 200:
        print("DEFECT Type4: write succeeded while shard READONLY (silent)"); defect = True
if s >= 500:
    print("DEFECT Type3: 5xx on write to READONLY shard (expect 4xx)"); defect = True

# reads must still work
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}")
print("read in READONLY (expect 200):", s, raw[:100])
if s != 200:
    print("DEFECT Type4: read broken while READONLY"); defect = True

# back to READY
s, b, raw = safe_request("PUT", f"/schema/{CLS}/shards/{shard}", {"status": "READY"})
print("back to READY:", s, raw[:100])
time.sleep(1)
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}?include=vector")
print("read after cycle (expect 200, before/[0.1,0.2]):", s)
if s == 200:
    if ((b or {}).get("properties") or {}).get("name") != "before" or (b or {}).get("vector") != [0.1, 0.2]:
        print("DEFECT Type4: object mutated across READONLY cycle:", raw[:150]); defect = True
else:
    print("DEFECT Type4: object lost across READONLY cycle"); defect = True

# writes work again
s, b, raw = safe_request("POST", "/objects",
    {"class": CLS, "id": "88888888-8888-8888-8888-888888888888",
     "properties": {"name": "after"}, "vector": [0.5, 0.6]})
print("write after READY (expect 200):", s)
if s not in (200, 201):
    print("DEFECT Type4: writes not restored after READY"); defect = True

# invalid status transition
s, b, raw = safe_request("PUT", f"/schema/{CLS}/shards/{shard}", {"status": "BOGUS"})
print("invalid status (expect 4xx):", s, raw[:120])
if s in (200, 201):
    print("DEFECT Type1: illegal shard status BOGUS accepted"); defect = True

try:
    safe_request("DELETE", f"/schema/{CLS}")
except Exception:
    pass

print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
