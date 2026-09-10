# state_recreate_residue_001 — delete class -> recreate same name: old object state residue
# Attack: count_consistency / delete_consistency (lifecycle recreate)
# Blindspot: state residue after class recreation
import os, sys, json, requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE = BASE.rstrip("/") + "/v1"
S = requests.Session()

def safe_request(method, path, body=None, hdrs=None):
    try:
        r = S.request(method, BASE + path, json=body, headers=hdrs or {}, timeout=30)
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, r.text
    except Exception as e:
        return -1, None, str(e)

CLS = "StR001"
OID = "11111111-1111-1111-1111-111111111111"
CLS_BODY = {"class": CLS, "vectorizer": "none",
            "properties": [{"name": "name", "dataType": ["text"]}]}

# cleanup
safe_request("DELETE", f"/schema/{CLS}")
import time; time.sleep(1)

s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("create1:", s, raw[:200]); assert s in (200, 201), "setup fail"

s, b, raw = safe_request("POST", "/objects",
    {"class": CLS, "id": OID, "properties": {"name": "old"}, "vector": [0.1, 0.2, 0.3]})
print("insert old obj:", s, raw[:200])

s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}")
print("get old obj before delete:", s)

# delete class
s, b, raw = safe_request("DELETE", f"/schema/{CLS}")
print("delete class:", s, raw[:200])
time.sleep(1)

s, b, raw = safe_request("GET", f"/schema/{CLS}")
print("schema after delete (expect 404):", s)
s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}")
print("orphan object get after class delete (expect 404):", s, raw[:200])
s, b, raw = safe_request("GET", f"/objects?class={CLS}&limit=100")
print("orphan list after class delete:", s, "totalResults=", (b or {}).get("totalResults") if isinstance(b, dict) else raw[:150])

# recreate same name
s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("recreate same name:", s, raw[:200])
time.sleep(1)

s, b, raw = safe_request("GET", f"/objects/{CLS}/{OID}")
print("old object after recreate (expect 404 = no residue):", s, raw[:200])
s, b, raw = safe_request("GET", f"/objects?class={CLS}&limit=100")
tot = (b or {}).get("totalResults") if isinstance(b, dict) else None
print("list after recreate, totalResults (expect 0):", s, tot)

defect = False
if s != 404 and False: pass
s2, b2, raw2 = safe_request("GET", f"/objects/{CLS}/{OID}")
if s2 == 200:
    print("DEFECT: old object resurrected after class recreate")
    defect = True
if isinstance(tot, int) and tot > 0:
    print(f"DEFECT: {tot} residual objects in recreated class")
    defect = True

# reuse same id in new class should work
s, b, raw = safe_request("POST", "/objects",
    {"class": CLS, "id": OID, "properties": {"name": "new"}, "vector": [0.4, 0.5, 0.6]})
print("re-insert same id in recreated class:", s, raw[:200])
if s not in (200, 201):
    print("DEFECT: cannot reuse object id after class recreate:", s)
    defect = True

try:
    safe_request("DELETE", f"/schema/{CLS}")
except Exception:
    pass

print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
