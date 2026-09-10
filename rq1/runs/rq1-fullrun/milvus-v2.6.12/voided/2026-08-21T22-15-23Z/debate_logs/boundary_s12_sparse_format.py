# boundary: SparseFloatVector literal format (insert + search)
# Attack: type boundary (strategy 2)
# Constraint: milvus_type_collections_create_004 — sparse literal JSON input format
# exploration_target: novel
# Blindspot: BS-01
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, cleanup_drop_collection

CN = "bnd_s12_sp"


def main():
    cleanup_drop_collection(CN)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": CN,
        "schema": {"autoId": False, "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "SparseFloatVector"}]},
        "indexParams": [{"fieldName": "vector", "indexName": "vi",
                         "metricType": "IP", "params": {"index_type": "AUTOINDEX"}}]})
    if not is_ok(st, bd):
        print("SETUP_FAIL s12 %s" % raw); print("VERDICT_SCRIPT_ERROR"); return
    req("POST", "collections+load", {"collectionName": CN})
    rs = []
    # insert-side format cases
    for label, vec, expect_err in [
            ("dict {1:0.5} (ok)", {"1": 0.5}, False),
            ("dict neg index {-1:0.5}", {"-1": 0.5}, True),
            ("dict non-numeric key {a:0.5}", {"a": 0.5}, True),
            ("dict empty {}", {}, True),
            ("dict value str", {"1": "x"}, True),
            ("list [0.1,0.2] (dense form)", [0.1, 0.2], True),
            ("nested dict", {"1": {"2": 0.5}}, True)]:
        st, bd, raw = req("POST", "entities+insert",
                          {"collectionName": CN, "data": [{"id": 1, "vector": vec}]})
        ok = is_ok(st, bd)
        print("CASE %-30s ok=%s | %s" % (label, ok, raw[:140]))
        if expect_err and ok:
            print("VERDICT_DEFECT 1 s12 %s accepted" % label); rs.append(False)
        if (not expect_err) and not ok:
            print("VERDICT_DEFECT 3 s12 %s rejected" % label); rs.append(False)
    # search-side: dense-style list as sparse data
    st, bd, raw = req("POST", "entities+search",
                      {"collectionName": CN, "data": [[0.1, 0.2]], "limit": 3})
    ok = is_ok(st, bd)
    print("CASE %-30s ok=%s | %s" % ("search sparse w/ dense list", ok, raw[:140]))
    if ok:
        print("VERDICT_DEFECT 1 s12 dense-list search accepted"); rs.append(False)
    st, bd, raw = req("POST", "entities+search",
                      {"collectionName": CN, "data": [{"1": 0.5}], "limit": 3})
    print("CASE %-30s ok=%s | %s" % ("search sparse dict (ok)", is_ok(st, bd), raw[:140]))
    if not is_ok(st, bd):
        print("VERDICT_DEFECT 3 s12 valid sparse search rejected"); rs.append(False)
    cleanup_drop_collection(CN)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
