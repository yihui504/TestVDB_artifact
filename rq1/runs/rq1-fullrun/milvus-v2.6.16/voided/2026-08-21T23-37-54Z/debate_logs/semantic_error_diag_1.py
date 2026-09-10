# script_id: semantic_error_diag_1
# Attack: 错误诊断质量——v2 错误信封 message 质量（错误 code 正确性 + message 是否指明参数/上下文）
# Constraints: milvus_bc_envelope_v2_001, milvus_state_collections_describe_001, milvus_state_collections_create_002
# source_url: .milvus-src-2616 (contract), doc_version: unknown
import os, sys, time
import requests

BASE = os.environ.get("TESTVDB_DB_URL")
TOKEN = os.environ.get("TESTVDB_DB_TOKEN", "root:Milvus")
if not BASE:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
H = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

def sr(path, body=None, raw_body=None):
    try:
        if raw_body is not None:
            r = requests.post(BASE + "/v2/vectordb/" + path, data=raw_body, headers=H, timeout=60)
        else:
            r = requests.post(BASE + "/v2/vectordb/" + path, json=body if body is not None else {}, headers=H, timeout=60)
        raw = r.text
        try:
            b = r.json()
        except Exception:
            b = None
        return r.status_code, b, raw
    except Exception as e:
        return -1, None, str(e)

CL = "sm_errdiag_1"
def cleanup():
    try: sr("collections/drop", {"collectionName": CL})
    except Exception: pass

def check(label, s, b, raw, want_code, msg_must_contain=()):
    print("%-42s http=%s code=%s msg=%s" % (label, s, (b or {}).get("code"), str((b or {}).get("message"))[:110]))
    if not isinstance(b, dict):
        return ("%s: response not JSON envelope" % label, raw[:120])
    code = b.get("code")
    msg = str(b.get("message") or "")
    if want_code is not None and code != want_code:
        return ("%s: code %s expected %s" % (label, code, want_code), msg[:150])
    for frag in msg_must_contain:
        if frag and frag not in msg:
            return ("%s: message lacks diagnostic context %r (msg=%r)" % (label, frag, msg[:100]), "")
    return None

def main():
    defects = []
    cleanup(); time.sleep(1)
    s, b, raw = sr("collections/create", {"collectionName": CL, "dimension": 4, "idType": "Int64", "metricType": "L2"})
    if not (isinstance(b, dict) and b.get("code") == 0):
        print("VERDICT: SCRIPT_ERROR"); cleanup(); sys.exit(2)

    cases = [
        # (label, path, body/raw, expected_code, message must contain)
        ("describe nonexistent", "collections/describe", ({"collectionName": "no_such"}, None), 100, ("no_such",)),
        ("has nonexistent (expect has:false)", "collections/has", ({"collectionName": "no_such"}, None), 0, ()),
        ("get_stats nonexistent", "collections/get_stats", ({"collectionName": "no_such"}, None), 100, ("no_such",)),
        ("search nonexistent", "entities/search", ({"collectionName": "no_such", "data": [0.1] * 4}, None), 100, ("no_such",)),
        ("insert nonexistent", "entities/insert", ({"collectionName": "no_such", "data": [{"id": 1, "vector": [0.1] * 4}]}, None), 100, ("no_such",)),
        ("drop nonexistent", "collections/drop", ({"collectionName": "no_such"}, None), 100, ("no_such",)),
        ("load nonexistent", "collections/load", ({"collectionName": "no_such"}, None), 100, ("no_such",)),
        ("describe missing param", "collections/describe", ({}, None), 1802, ()),
        ("create dbName nonexistent", "collections/create", ({"collectionName": "sm_x", "dbName": "no_such_db", "dimension": 4, "idType": "Int64"}, None), 800, ("no_such_db",)),
        ("search bad consistencyLevel", "entities/search", ({"collectionName": CL, "data": [0.1] * 4, "consistencyLevel": "Bogus"}, None), 1100, ("Bogus",)),
        ("insert wrong dim", "entities/insert", ({"collectionName": CL, "data": [{"id": 1, "vector": [0.1, 0.2]}]}, None), None, ()),
        ("index describe nonexistent", "indexes/describe", ({"collectionName": CL, "indexName": "no_idx"}, None), 700, ("no_idx",)),
        ("alias alter nonexistent alias", "aliases/alter", ({"aliasName": "no_alias_zz", "collectionName": CL}, None), 1600, ()),
        ("malformed json", "collections/list", (None, b"{not json"), 1801, ()),
    ]
    for label, path, (body, rawb), want, frags in cases:
        d = check(label, s if False else 0, *(sr(path, body, rawb)), want_code=want, msg_must_contain=frags) if False else None
        st, bb, rr = sr(path, body, rawb)
        d = check(label, st, bb, rr, want, frags)
        if d:
            defects.append(d)

    cleanup()
    for d in defects: print("DEFECT:", d)
    if defects:
        print("VERDICT: DEFECT_FOUND"); sys.exit(1)
    print("VERDICT: NO_DEFECT"); sys.exit(0)

try:
    main()
except Exception as e:
    print("EXC:", e)
    try: cleanup()
    except Exception: pass
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
