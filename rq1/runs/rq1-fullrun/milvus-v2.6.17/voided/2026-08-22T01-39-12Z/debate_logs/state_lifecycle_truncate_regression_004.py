# state: truncate/drop lifecycle regression — truncate zero count preserving load state; drop-then-access 404/code100
# Attack: strategy 1/2 (count + delete consistency) x milvus_inv_truncate_count_001 + milvus_inv_dropped_absent_001
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib import safe_request, code_of, create_collection, load_collection, drop_collection, query_all, get_stats

CLS = "st_trunc_004"
verdict, detail = "NO_DEFECT", ""
try:
    drop_collection(CLS)
    s, b, raw = create_collection(CLS, with_array=False)
    if code_of(b) != 0:
        raise RuntimeError("create failed: " + raw)
    load_collection(CLS)
    for i in range(5):
        safe_request("POST", "entities+insert", {"collectionName": CLS, "data": [
            {"id": i, "vec": [0.1] * 8}]})
    _, rc0, raw = get_stats(CLS)
    print("stats pre-truncate:", raw)
    s, b, raw = safe_request("POST", "collections+truncate", {"collectionName": CLS})
    print("truncate:", raw)
    time.sleep(1)
    _, rc, raw = get_stats(CLS)
    print("stats post-truncate:", raw)
    if rc != 0:
        verdict, detail = "DEFECT_FOUND", "truncate left rowCount=%s" % rc
    # load state preserved? query (needs load) should still be code 0, empty
    s, b, raw = query_all(CLS)
    print("query post-truncate:", raw)
    if code_of(b) == 101:
        verdict, detail = "DEFECT_FOUND", "truncate released collection (query -> 101)"
    # drop then access
    drop_collection(CLS)
    s, b, raw = safe_request("POST", "collections+describe", {"collectionName": CLS})
    print("describe post-drop:", raw)
    if code_of(b) != 100:
        verdict, detail = "DEFECT_FOUND", "describe after drop should code 100, got %s" % code_of(b)
except Exception as e:
    verdict, detail = "SCRIPT_ERROR", str(e)
finally:
    drop_collection(CLS)
print(detail)
print("VERDICT: %s" % verdict)
