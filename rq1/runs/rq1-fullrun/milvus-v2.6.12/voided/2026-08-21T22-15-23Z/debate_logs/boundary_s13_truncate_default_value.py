# boundary: truncate boundaries + defaultValue fillWithValue
# Attack: state/boundary (strategies 1/2)
# Constraints: milvus_state_collections_truncate_001 (truncate resets rows, keeps schema/index/load),
#              defaultValue fillWithValue (v2.6 validate_util adaptation)
# exploration_target: regression + novel
# Blindspot: BS-04
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, cleanup_drop_collection

CN = "bnd_s13_tr"


def setup():
    cleanup_drop_collection(CN)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": CN,
        "schema": {"autoId": False, "enableDynamicField": True, "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "tag", "dataType": "VarChar",
             "elementTypeParams": {"max_length": "64"},
             "defaultValue": "fillme"},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "4"}}]},
        "indexParams": [{"fieldName": "vector", "indexName": "vi",
                         "metricType": "L2", "params": {"index_type": "AUTOINDEX"}}]})
    if not is_ok(st, bd):
        return False, raw
    req("POST", "collections+load", {"collectionName": CN})
    req("POST", "entities+insert", {"collectionName": CN,
                                    "data": [{"id": 1, "vector": [0.1] * 4},
                                             {"id": 2, "tag": "x", "vector": [0.2] * 4}]})
    return True, ""


def main():
    ok, err = setup()
    if not ok:
        print("SETUP_FAIL s13 %s" % err); print("VERDICT_SCRIPT_ERROR"); return
    rs = []
    # defaultValue read-back
    st, bd, raw = req("POST", "entities+get", {"collectionName": CN, "id": 1,
                                               "outputFields": ["tag"]})
    print("CASE default fill read-back ok=%s | %s" % (is_ok(st, bd), raw[:150]))
    # truncate then verify
    st, bd, raw = req("POST", "collections+truncate", {"collectionName": CN})
    print("CASE truncate ok=%s | %s" % (is_ok(st, bd), raw[:120]))
    if not is_ok(st, bd):
        print("VERDICT_DEFECT 3 s13 truncate failed"); rs.append(False)
    # rows reset?
    st, bd, raw = req("POST", "entities+query",
                      {"collectionName": CN, "filter": "id >= 0", "limit": 10})
    rows = bd.get("data", []) if isinstance(bd, dict) else []
    print("CASE post-truncate query rows=%s | %s" % (len(rows), raw[:120]))
    if rows:
        print("VERDICT_DEFECT 1 s13 rows survive truncate"); rs.append(False)
    # search still works (index/load preserved)
    st, bd, raw = req("POST", "entities+search",
                      {"collectionName": CN, "data": [[0.1] * 4], "limit": 3})
    print("CASE post-truncate search ok=%s | %s" % (is_ok(st, bd), raw[:120]))
    if not is_ok(st, bd):
        print("VERDICT_DEFECT 3 s13 search after truncate failed"); rs.append(False)
    # truncate nonexistent
    st, bd, raw = req("POST", "collections+truncate", {"collectionName": "bnd_s13_nope"})
    print("CASE truncate nonexistent ok=%s | %s" % (is_ok(st, bd), raw[:130]))
    if is_ok(st, bd):
        print("VERDICT_DEFECT 1 s13 truncate nonexistent accepted"); rs.append(False)
    # re-insert after truncate (schema intact, defaultValue again)
    st, bd, raw = req("POST", "entities+insert",
                      {"collectionName": CN, "data": [{"id": 3, "vector": [0.3] * 4}]})
    print("CASE re-insert after truncate ok=%s | %s" % (is_ok(st, bd), raw[:120]))
    if not is_ok(st, bd):
        print("VERDICT_DEFECT 3 s13 re-insert after truncate failed"); rs.append(False)
    cleanup_drop_collection(CN)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
