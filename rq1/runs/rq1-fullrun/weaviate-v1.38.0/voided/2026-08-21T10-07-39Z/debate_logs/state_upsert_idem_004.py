# state_upsert_idem_004 — same-ID repeated upsert: count, merge semantics, PATCH partial merge
# Attack: upsert_idempotence (count consistency + last-write-wins + patch merge atomicity)
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

CLS = "StU004"
OID = "44444444-4444-4444-4444-444444444444"
CLS_BODY = {"class": CLS, "vectorizer": "none",
            "properties": [{"name": "name", "dataType": ["text"]},
                           {"name": "tag", "dataType": ["text"]}]}

safe_request("DELETE", f"/schema/{CLS}")
time.sleep(1)
s, b, raw = safe_request("POST", "/schema", CLS_BODY)
print("create:", s); assert s in (200, 201)

def count():
    s, b, raw = safe_request("GET", f"/objects?class={CLS}&limit=1")
    tot = (b or {}).get("totalResults") if isinstance(b, dict) else None
    if tot is None:
        # fallback: graphql aggregate
        q = '{"query":"{ Aggregate { StU004 { meta { count } } } }"}'
        r = S.post(BASE + "/graphql", data=q, headers={"Content-Type": "application/json"})
        try:
            tot = r.json()["data"]["Aggregate"][CLS][0]["meta"]["count"]
        except Exception:
            tot = None
    return s, tot

def get_obj():
    return safe_request("GET", f"/objects/{CLS}/{OID}?include=vector")

defect = False

# 1. POST same ID twice -> exactly one object
s1, _, _ = safe_request("POST", "/objects",
    {"class": CLS, "id": OID, "properties": {"name": "v1", "tag": "a"}, "vector": [0.1, 0.2]})
s2, _, _ = safe_request("POST", "/objects",
    {"class": CLS, "id": OID, "properties": {"name": "v2", "tag": "b"}, "vector": [0.3, 0.4]})
print("POST #1:", s1, "POST #2 (same id):", s2)
time.sleep(1)
s, tot = count()
print("totalResults after 2 same-id POSTs (expect 1):", tot)
if tot != 1:
    print(f"DEFECT Type4: count={tot}, expected 1"); defect = True

s, b, raw = get_obj()
print("object after 2 POSTs:", s, raw[:150])
if s == 200:
    props = (b or {}).get("properties") or {}
    vec = (b or {}).get("vector")
    print("props:", props, "vector:", vec)
    if props.get("name") not in ("v1", "v2"):
        print("DEFECT Type4: unexpected property state"); defect = True
    # last write wins: expect v2/b/[0.3,0.4] (weaviate POST = replace)
    if props.get("name") == "v2" and props.get("tag") == "b" and vec != [0.3, 0.4]:
        print("DEFECT Type4: vector not replaced with properties on upsert:", vec); defect = True
    # partial-merge violation: v2 with stale tag a from v1
    if props.get("name") == "v2" and props.get("tag") == "a":
        print("DEFECT Type4: partial merge across upserts (new name + stale tag)"); defect = True

# 2. PATCH partial update: only 'name' -> 'tag' must be preserved
s, b, raw = safe_request("PATCH", f"/objects/{CLS}/{OID}",
    {"properties": {"name": "v3"}})
print("PATCH name-only:", s, raw[:150])
time.sleep(1)
s, b, raw = get_obj()
print("after PATCH:", s, raw[:200])
if s == 200:
    props = (b or {}).get("properties") or {}
    if props.get("name") != "v3" or "tag" not in props:
        print(f"DEFECT Type4: PATCH clobbered unrelated property: {props}"); defect = True
    # vector must be untouched by PATCH
    if (b or {}).get("vector") in (None, []):
        print("DEFECT Type4: PATCH dropped vector"); defect = True

# 3. PUT /objects/{id} upsert (no class segment) with same id
s, b, raw = safe_request("PUT", f"/objects/{OID}",
    {"class": CLS, "id": OID, "properties": {"name": "v4", "tag": "v4"}, "vector": [0.5, 0.6]})
print("PUT /objects/{id}:", s, raw[:120])
time.sleep(1)
s, tot = count()
print("count after PUT (expect 1):", tot)
if tot != 1:
    print(f"DEFECT Type4: PUT by-id changed count to {tot}"); defect = True

# 4. concurrent same-id upserts (race) -> count stays 1, no torn state
import threading
def racer(i):
    safe_request("POST", "/objects",
        {"class": CLS, "id": OID, "properties": {"name": f"r{i}", "tag": f"r{i}"}, "vector": [0.1 * i, 0.2]})
ts = [threading.Thread(target=racer, args=(i,)) for i in range(8)]
[t.start() for t in ts]; [t.join() for t in ts]
time.sleep(2)
s, tot = count()
print("count after 8 concurrent same-id POSTs (expect 1):", tot)
if tot != 1:
    print(f"DEFECT Type4: concurrent same-id upsert produced count={tot}"); defect = True
s, b, raw = get_obj()
if s == 200:
    props = (b or {}).get("properties") or {}
    if props.get("name") != props.get("tag"):
        print(f"DEFECT Type4: torn write: name={props.get('name')} tag={props.get('tag')}"); defect = True

try:
    safe_request("DELETE", f"/schema/{CLS}")
except Exception:
    pass

print("VERDICT: DEFECT_FOUND" if defect else "VERDICT: NO_DEFECT")
sys.exit(1 if defect else 0)
