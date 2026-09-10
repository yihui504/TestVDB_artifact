# script_id: vein_newcode_truncate_rename_008
# Attack: vein strategy 2.6.x new code-path maturity: truncate (NEW in 2.6.12) x rename x load-state interplay
"""
Controlled comparison on fresh collections:
 A. truncate on nonexistent collection -> error code/HTTP sanity
 B. truncate on empty collection -> code 0
 C. truncate on loaded collection with rows -> rowCount reset 0, schema+load preserved (milvus_inv_truncate_count_001)
 D. rename after truncate -> old name gone, new name has empty stats
 E. insert after truncate -> works
Defect: 5xx anywhere, rowCount not reset, schema changed, rename to truncated name corrupt.
"""
import sys, time
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code, drop, wait_flush, row_count

CL = "vn_trunc_008"; CL2 = "vn_trunc_008_b"; NX = "vn_trunc_008_nx"
VERDICT = "SCRIPT_ERROR"
try:
    drop(CL); drop(CL2)
    # A
    s, b, raw = safe_request("POST", "collections+truncate", {"collectionName": NX})
    print("truncate nx:", s, raw[:200])
    if s >= 500 or code(b) == 0:
        print("DEFECT: truncate nx -> HTTP %s code %s" % (s, code(b))); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    # B/C
    s, b, raw = safe_request("POST", "collections+create", {"collectionName": CL, "dimension": 4})
    print("create:", s, raw[:120]); assert code(b) == 0
    _, b, raw = safe_request("POST", "collections+describe", {"collectionName": CL})
    schema_before = ((b or {}).get("data") or {})
    s, b, raw = safe_request("POST", "collections+load", {"collectionName": CL})
    print("load:", s, raw[:120])
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL, "data": [
        {"id": i, "vector": [0.1] * 4} for i in range(1, 6)]})
    print("insert 5:", s, raw[:150]); assert code(b) == 0
    time.sleep(2)
    _, bq, rawq = safe_request("POST", "entities+query", {"collectionName": CL, "filter": "id >= 1", "outputFields": ["id"]})
    rc0 = len((bq or {}).get("data") or []); print("query-visible pre-truncate:", rc0)
    s, b, raw = safe_request("POST", "collections+truncate", {"collectionName": CL})
    print("truncate:", s, raw[:200])
    if s >= 500 or code(b) != 0:
        print("DEFECT: truncate failed: %s" % raw[:150]); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    time.sleep(2)
    _, bq, rawq = safe_request("POST", "entities+query", {"collectionName": CL, "filter": "id >= 1", "outputFields": ["id"]})
    rc1 = len((bq or {}).get("data") or []); print("query-visible post-truncate:", rc1, rawq[:150])
    if rc1 != 0:
        print("DEFECT: rowCount %s after truncate (inv milvus_inv_truncate_count_001)" % rc1)
        VERDICT = "DEFECT_FOUND"; sys.exit(1)
    _, b, raw = safe_request("POST", "collections+describe", {"collectionName": CL})
    if code(b) != 0:
        print("DEFECT: describe after truncate -> code %s" % code(b)); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    _, b, raw = safe_request("POST", "collections+get_load_state", {"collectionName": CL})
    print("load state after truncate:", raw[:200])
    # D rename
    s, b, raw = safe_request("POST", "collections+rename", {"collectionName": CL, "newCollectionName": CL2})
    print("rename:", s, raw[:200])
    if s >= 500 or code(b) != 0:
        print("DEFECT: rename after truncate failed: %s" % raw[:150]); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    _, b, raw = safe_request("POST", "collections+has", {"collectionName": CL})
    has_old = ((b or {}).get("data") or {}).get("has")
    _, b, raw = safe_request("POST", "collections+has", {"collectionName": CL2})
    has_new = ((b or {}).get("data") or {}).get("has")
    print("has old/new:", has_old, has_new)
    if has_old or not has_new:
        print("DEFECT: rename state broken"); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    # E insert after truncate+rename
    s, b, raw = safe_request("POST", "entities+insert", {"collectionName": CL2, "data": [{"id": 9, "vector": [0.2] * 4}]})
    print("insert after truncate+rename:", s, raw[:200])
    if s >= 500 or code(b) != 0:
        print("DEFECT: insert after truncate+rename failed"); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    drop(CL); drop(CL2); drop(NX)
    print("VERDICT: %s" % VERDICT)
