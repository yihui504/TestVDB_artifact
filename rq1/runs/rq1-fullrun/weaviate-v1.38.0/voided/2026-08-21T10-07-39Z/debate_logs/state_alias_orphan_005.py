# state_alias_orphan_005 — alias lifecycle: delete aliased class -> orphan alias behavior
# Attack: dependency-chain break (Mode C) + alias pointing at deleted class; recreate; alias-of-alias
# Probe fact (v1.38.0): alias creation is POST /aliases {"alias": ..., "class": ...}
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

CLS = "StA005"
OID = "55555555-5555-5555-5555-555555555555"
ALIAS = "StA005_alias"
CLS_BODY = {"class": CLS, "vectorizer": "none",
            "properties": [{"name": "name", "dataType": ["text"]}]}

safe_request("DELETE", f"/aliases/{ALIAS}")
safe_request("DELETE", f"/schema/{CLS}")
time.sleep(1)

s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("create:", s); assert s in (200, 201)
s, b, raw = safe_request("POST", "/objects",
    {"class": CLS, "id": OID, "properties": {"name": "x"}, "vector": [0.1, 0.2]})
print("insert:", s)

# alias-of-alias must be rejected (no chains)
s, b, raw = safe_request("POST", "/aliases", {"alias": ALIAS, "class": ALIAS})
print("alias-of-alias (expect 4xx):", s, raw[:120])

s, b, raw = safe_request("POST", "/aliases", {"alias": ALIAS, "class": CLS})
print("create alias:", s, raw[:100])

s, b, raw = safe_request("GET", f"/objects/{ALIAS}/{OID}")
print("get via alias (expect 200):", s)
defect = False
if s != 200:
    print("DEFECT Type4: object unreadable through valid alias"); defect = True

# delete target class -> alias becomes orphan
s, b, raw = safe_request("DELETE", f"/schema/{CLS}")
print("delete class:", s)
time.sleep(1)

s, b, raw = safe_request("GET", f"/aliases/{ALIAS}")
print("GET alias after target deleted:", s, raw[:120])
s2, b2, raw2 = safe_request("GET", f"/objects/{ALIAS}/{OID}")
print("read via orphan alias:", s2, raw2[:120])
if s2 == 200:
    print("DEFECT Type4: orphan alias serves object of deleted class"); defect = True
if s2 >= 500:
    print("DEFECT Type3: 5xx reading via orphan alias"); defect = True

# recreate class: alias must NOT resurrect old object
s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("recreate class:", s)
time.sleep(1)
s, b, raw = safe_request("GET", f"/objects/{ALIAS}/{OID}")
print("get via alias after recreate (expect 404):", s, raw[:100])
if s == 200:
    print("DEFECT Type4: alias resurrects pre-delete object after class recreate"); defect = True
if s >= 500:
    print("DEFECT Type3: 5xx via alias after recreate"); defect = True

# alias update to nonexistent class must be rejected
s, b, raw = safe_request("PUT", f"/aliases/{ALIAS}", {"class": "StA005_nonexistent"})
print("PUT alias -> nonexistent (expect 4xx):", s, raw[:150])
if s in (200, 201):
    s2, b2, raw2 = safe_request("GET", f"/objects/{ALIAS}/{OID}")
    if s2 == 200:
        print("DEFECT Type4: alias to nonexistent class still serves data"); defect = True
    if s2 >= 500:
        print("DEFECT Type3: 5xx via alias to nonexistent class"); defect = True

try:
    safe_request("DELETE", f"/aliases/{ALIAS}")
    safe_request("DELETE", f"/schema/{CLS}")
except Exception:
    pass

print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
