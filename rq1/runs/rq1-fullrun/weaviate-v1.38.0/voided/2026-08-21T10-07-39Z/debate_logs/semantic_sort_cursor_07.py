# Attack: sort semantics + cursor pagination semantics (no duplication, no loss, deterministic order)
# Target: weaviate v1.38.0 | Endpoint: POST /v1/graphql | Strategy: search_correctness / metamorphic
# SKIPPED by-design: `after` cannot combine with `sort` + `limit` (documented cursor API constraint);
#                   cursor pagination uses id order by default. Sort correctness tested standalone.
import os, sys, json, uuid
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
if not BASE:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set"); sys.exit(2)
BASE = BASE.rstrip("/")
CLS = "SemCursor07"

def safe_request(method, path, json_body=None, data=None):
    headers = {"Content-Type": "application/json"}
    try:
        r = requests.request(method, BASE + path, json=json_body, data=data, headers=headers, timeout=30)
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, str(e)

safe_request("DELETE", f"/v1/schema/{CLS}")
schema = {"class": CLS, "vectorizer": "none",
          "properties": [{"name": "name", "dataType": ["text"]},
                         {"name": "score", "dataType": ["number"]},
                         {"name": "grp", "dataType": ["text"]}]}
status, _, raw = safe_request("POST", "/v1/schema", json_body=schema)
if status not in (200, 201):
    print("VERDICT: SCRIPT_ERROR - create class failed:", status, raw[:300]); sys.exit(2)

names = []
for i in range(10):
    nm = "obj%02d" % i
    names.append(nm)
    status, _, raw = safe_request("POST", "/v1/objects",
        json_body={"class": CLS, "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, CLS + nm)),
                   "properties": {"name": nm, "score": i, "grp": "same"}})
    if status not in (200, 201):
        print("VERDICT: SCRIPT_ERROR - insert failed:", status, raw[:300]); sys.exit(2)

import time; time.sleep(1)
failures = []

def gql(q):
    st, b, raw = safe_request("POST", "/v1/graphql", data=json.dumps({"query": q}))
    res = ((b or {}).get("data") or {}).get("Get", {}).get(CLS) or []
    errs = (b or {}).get("errors")
    return st, res, errs, raw

# T1: cursor pagination (after, default id order) — no dup/loss
seen, cursor, pages = [], None, 0
while pages < 8:
    args = 'limit: 3' + (', after: "%s"' % cursor if cursor else '')
    q = '{ Get { %s(%s) { name _additional { id } } } }' % (CLS, args)
    st, res, errs, raw = gql(q)
    if errs:
        print("page error:", json.dumps(errs)[:250])
        failures.append(("pagination error", errs, raw[:200]))
        break
    if not res:
        break
    seen.extend(o["name"] for o in res)
    cursor = res[-1]["_additional"]["id"]
    pages += 1
print("T1 cursor pages:", pages, "seen count:", len(seen))

dupes = sorted(set(n for n in seen if seen.count(n) > 1))
if dupes: failures.append(("T2 duplicates across pages", dupes, seen))
missing = sorted(set(names) - set(seen))
if missing: failures.append(("T2 lost objects across pages", missing, seen))
extra = sorted(set(seen) - set(names))
if extra: failures.append(("T2 phantom objects", extra, seen))

# T3: sort by score asc — strictly ascending order, all 10
st, res, errs, raw = gql('{ Get { %s(limit: 10, sort: {path: ["score"], order: asc}) { name score } } }' % CLS)
sc = [o["score"] for o in res]
print("T3 sort asc:", st, sc, json.dumps(errs)[:150] if errs else "")
if not errs and (sc != list(range(10)) or len(res) != 10):
    failures.append(("T3 asc sort wrong", sc, raw[:250]))

# T4: sort desc — strictly descending
st, res, errs, raw = gql('{ Get { %s(limit: 10, sort: {path: ["score"], order: desc}) { score } } }' % CLS)
sc = [o["score"] for o in res]
print("T4 sort desc:", st, sc)
if not errs and sc != list(range(9, -1, -1)):
    failures.append(("T4 desc sort wrong", sc, raw[:250]))

# T5: sort asc on text name (lowercase alnum, no stopwords)
st, res, errs, raw = gql('{ Get { %s(limit: 10, sort: {path: ["name"], order: asc}) { name } } }' % CLS)
got = [o["name"] for o in res]
print("T5 text sort asc:", st, got, json.dumps(errs)[:150] if errs else "")
if not errs and got != sorted(names):
    failures.append(("T5 text asc sort wrong", got, raw[:250]))

# T6: tie sort on grp (all same) — complete, no loss
st, res, errs, raw = gql('{ Get { %s(limit: 10, sort: {path: ["grp"], order: asc}) { name } } }' % CLS)
print("T6 tie sort:", st, len(res), json.dumps(errs)[:150] if errs else "")
if not errs and len(res) != 10:
    failures.append(("T6 tie sort lost objects", len(res), raw[:300]))

# T7: metamorphic — asc limit 3 == first 3 of full asc
st, res, errs, raw = gql('{ Get { %s(limit: 3, sort: {path: ["score"], order: asc}) { name } } }' % CLS)
top3 = [o["name"] for o in res]
st2, res2, errs2, raw2 = gql('{ Get { %s(limit: 10, sort: {path: ["score"], order: asc}) { name } } }' % CLS)
full = [o["name"] for o in res2]
print("T7 limit-3 prefix:", top3, "vs full[:3]", full[:3])
if not errs and not errs2 and top3 != full[:3]:
    failures.append(("T7 limit truncation not prefix", top3, full[:3]))

try:
    safe_request("DELETE", f"/v1/schema/{CLS}")
except Exception:
    pass

if failures:
    print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
    for f in failures: print("FAIL:", f)
    sys.exit(1)
print("VERDICT: NO_DEFECT")
