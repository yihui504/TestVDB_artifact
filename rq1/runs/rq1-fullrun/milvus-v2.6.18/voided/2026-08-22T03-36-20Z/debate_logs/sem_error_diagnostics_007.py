# script_id: sem_error_diagnostics_007
# Attack: semantic strategy error diagnostic quality across state-relevant endpoints
"""
Error-diagnosis quality: for a set of failure conditions the message must name the actual cause
(collection not found -> code 100 with collection name; drop nonexistent; insert into nonexistent;
search nonexistent collection code path is 100 not 500; upsert fieldOps unknown op -> 1100).
Defect: any HTTP 5xx, code 0 for clearly illegal op (e.g. upsert unknown fieldOps op accepted,
insert into nonexistent collection accepted).
"""
import sys
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code, drop

CL = "sem_diag_007"
NX = "sem_diag_007_nx"
VERDICT = "SCRIPT_ERROR"
fails = []
try:
    drop(CL); drop(NX)
    s, b, raw = safe_request("POST", "collections+create", {"collectionName": CL, "dimension": 4, "autoID": False, "idType": "Int64"})
    print("create:", s, raw[:150]); assert code(b) == 0

    checks = []
    # 1. describe nonexistent -> 100, message names collection
    s, b, raw = safe_request("POST", "collections+describe", {"collectionName": NX})
    print("describe nx:", s, raw[:200]); checks.append(("describe_nx", s, code(b), NX in raw))
    # 2. drop nonexistent -> 100 or idempotent-ok
    s, b, raw = safe_request("POST", "collections+drop", {"collectionName": NX})
    print("drop nx:", s, raw[:200]); checks.append(("drop_nx", s, code(b), True))
    # 3. insert into nonexistent -> must not be 0
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": NX, "data": [{"id": 1, "vector": [0.1] * 4}]})
    print("insert nx:", s, raw[:200]); checks.append(("insert_nx", s, code(b), code(b) != 0))
    # 4. upsert into nonexistent -> must not be 0
    s, b, raw = safe_request("POST", "entities+upsert", {"collectionName": NX, "data": [{"id": 1, "vector": [0.1] * 4}]})
    print("upsert nx:", s, raw[:200]); checks.append(("upsert_nx", s, code(b), code(b) != 0))
    # 5. search nonexistent -> not 0
    s, b, raw = safe_request("POST", "entities+search", {"collectionName": NX, "data": [[0.1] * 4]})
    print("search nx:", s, raw[:200]); checks.append(("search_nx", s, code(b), code(b) != 0))
    # 6. upsert unknown fieldOps op on real collection -> 1100
    s, b, raw = safe_request("POST", "entities+upsert", {"collectionName": CL,
        "data": [{"id": 1, "vector": [0.1] * 4}], "fieldOps": [{"fieldName": "vector", "op": "BOGUS_OP"}]})
    print("upsert bogus fieldOp:", s, raw[:250]); checks.append(("fieldops_bogus", s, code(b), code(b) == 1100))
    # 7. get with nonexistent collection -> 100
    s, b, raw = safe_request("POST", "entities+get", {"collectionName": NX, "id": 1})
    print("get nx:", s, raw[:200]); checks.append(("get_nx", s, code(b), code(b) == 100))

    for name, st, cd, ok in checks:
        if st >= 500:
            fails.append("%s -> HTTP %d" % (name, st))
        elif not ok:
            fails.append("%s -> code %s" % (name, cd))
    if fails:
        print("DEFECT: diagnostic failures: %s" % fails); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    drop(CL); drop(NX)
    print("VERDICT: %s" % VERDICT)
