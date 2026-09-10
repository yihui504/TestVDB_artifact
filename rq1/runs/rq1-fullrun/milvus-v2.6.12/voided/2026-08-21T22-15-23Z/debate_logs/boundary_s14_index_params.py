# boundary: index params (nlist) + search params (nprobe/ef/radius) extremes + malformed JSON
# Attack: numeric boundary + malformed input fuzz (strategies 1/6/7)
# Constraints: contract indexes+create params; search params float fields
# exploration_target: novel
# Blindspot: BS-04
# Live notes: raw NaN/Infinity tokens -> 1801 clean parse error (no coercion); client lib refuses
#             non-JSON floats, so NaN tests go through raw bodies. nprobe/ef are silently ignored
#             on AUTOINDEX (recorded for judge; not a crash).
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, create_float_collection, cleanup_drop_collection

CN = "bnd_s14_ix"
VEC = "[0.1,0.1,0.1,0.1,0.1,0.1,0.1,0.1]"


def main():
    ok1, err = create_float_collection(CN, dim=8)
    if not ok1:
        print("SETUP_FAIL s14 %s" % err); print("VERDICT_SCRIPT_ERROR"); return
    req("POST", "entities+insert", {"collectionName": CN, "data": [{"id": 1, "vector": [0.1] * 8}]})
    rs = []
    # search params extremes (strategy 6: crash/5xx is the defect)
    for label, params in [("nprobe=0", {"nprobe": 0}),
                          ("nprobe=-1", {"nprobe": -1}),
                          ("nprobe=1e9", {"nprobe": 1000000000}),
                          ("ef=0", {"ef": 0}),
                          ("ef=-5", {"ef": -5}),
                          ("radius=-1e308", {"radius": -1e308}),
                          ("radius=1e308", {"radius": 1e308})]:
        st, bd, raw = req("POST", "entities+search",
                          {"collectionName": CN, "data": [[0.1] * 8], "limit": 3,
                           "params": params})
        code = bd.get("code") if isinstance(bd, dict) else None
        crash = any(k in raw.lower() for k in ["panic", "oom", "internal error"])
        print("CASE %-16s status=%s code=%s | %s" % (label, st, code, raw[:130]))
        if st >= 500 or crash:
            print("VERDICT_DEFECT 2 s14 %s 5xx/crash" % label); rs.append(False)
    # malformed / NaN-raw JSON bodies (strategy 7): 4xx-equivalent (code 1801) is fine
    for label, blob in [
            ("truncated", ('{"collectionName":"%s","data":[%s,"limit":3}' % (CN, VEC)).encode()),
            ("trailing comma", ('{"collectionName":"%s","limit":3,}' % CN).encode()),
            ("single quotes", ("{'collectionName':'%s'}" % CN).encode()),
            ("NUL in body", ('{"collectionName":"%s\x00","limit":3}' % CN).encode()),
            ("radius=NaN raw", ('{"collectionName":"%s","data":[%s],"limit":3,"params":{"radius":NaN}}' % (CN, VEC)).encode()),
            ("radius=Inf raw", ('{"collectionName":"%s","data":[%s],"limit":3,"params":{"radius":Infinity}}' % (CN, VEC)).encode()),
            ("NaN vector raw", ('{"collectionName":"%s","data":[[NaN,NaN,NaN,NaN,NaN,NaN,NaN,NaN]],"limit":3}' % CN).encode())]:
        st, bd, raw = req("POST", "entities+search", raw_data=blob)
        crash = any(k in raw.lower() for k in ["panic", "oom", "internal error"])
        print("CASE %-16s status=%s | %s" % (label, st, raw[:130]))
        if st >= 500 or crash:
            print("VERDICT_DEFECT 2 s14 malformed %s 5xx/crash" % label); rs.append(False)
    # index create param extremes (HNSW zero params must be rejected)
    cn2 = "bnd_s14_nlist"
    cleanup_drop_collection(cn2)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": cn2,
        "schema": {"autoId": False, "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "8"}}]},
        "indexParams": [{"fieldName": "vector", "indexName": "vi", "metricType": "L2",
                         "params": {"index_type": "HNSW", "M": 0, "efConstruction": 0}}]})
    ok = is_ok(st, bd)
    print("CASE HNSW M=0 efC=0  ok=%s | %s" % (ok, raw[:130]))
    if ok or st >= 500:
        print("VERDICT_DEFECT 2 s14 HNSW zero params accepted/crash"); rs.append(False)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": cn2,
        "schema": {"autoId": False, "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "8"}}]},
        "indexParams": [{"fieldName": "vector", "indexName": "vi", "metricType": "L2",
                         "params": {"index_type": "HNSW", "M": 1000000,
                                    "efConstruction": 2147483647}}]})
    print("CASE HNSW huge M/efC ok=%s | %s" % (is_ok(st, bd), raw[:130]))
    if st >= 500:
        print("VERDICT_DEFECT 2 s14 HNSW huge params 5xx"); rs.append(False)
    cleanup_drop_collection(cn2)
    cleanup_drop_collection(CN)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
