# boundary: vector dimension max 32768 + dim mismatch insert
# Attack: numeric boundary + dimension mismatch (strategies 1/3)
# Constraint: milvus_range_collections_create_001 (dim max 32768);
#             milvus_type_entities_insert_001 (wrong dim -> ErrInvalidInsertData)
# exploration_target: regression + novel
# Blindspot: BS-04
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, cleanup_drop_collection


def mkcol(name, dim):
    cleanup_drop_collection(name)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": name,
        "schema": {"autoId": False, "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": str(dim)}}]},
        "indexParams": [{"fieldName": "vector", "indexName": "vi",
                         "metricType": "L2", "params": {"index_type": "AUTOINDEX"}}]})
    return is_ok(st, bd), raw


def main():
    rs = []
    # create-side dim boundaries
    for label, dim, expect_ok in [
            ("dim=1", 1, False), ("dim=2", 2, True), ("dim=0", 0, False), ("dim=-8", -8, False),  # live-confirmed: min dim is 2
            ("dim=32767", 32767, True), ("dim=32768", 32768, True),
            ("dim=32769", 32769, False), ("dim=100000", 100000, False),
            ("dim=65536", 65536, False)]:
        ok, raw = mkcol("bnd_s07_d%d" % (dim if dim > 0 else abs(dim) + 1000000), dim)
        print("CASE %-14s ok=%s | %s" % (label, ok, raw[:130]))
        if expect_ok and not ok:
            print("VERDICT_DEFECT 3 s07 %s rejected" % label); rs.append(False)
        if (not expect_ok) and ok:
            print("VERDICT_DEFECT 1 s07 %s accepted" % label); rs.append(False)
    # insert-side dim mismatch
    ok, raw = mkcol("bnd_s07_ins", 8)
    if not ok:
        print("SETUP_FAIL s07 %s" % raw); print("VERDICT_SCRIPT_ERROR"); return
    for label, vec, expect_err in [
            ("insert dim=4 (short)", [0.1] * 4, True),
            ("insert dim=16 (long)", [0.1] * 16, True),
            ("insert dim=8 (ok)", [0.1] * 8, False),
            ("insert empty vec", [], True)]:
        st, bd, r2 = req("POST", "entities+insert",
                         {"collectionName": "bnd_s07_ins", "data": [{"id": 2, "vector": vec}]})
        good = is_ok(st, bd)
        print("CASE %-22s ok=%s | %s" % (label, good, r2[:140]))
        if expect_err and good:
            print("VERDICT_DEFECT 1 s07 %s accepted" % label); rs.append(False)
        if (not expect_err) and not good:
            print("VERDICT_DEFECT 3 s07 %s rejected" % label); rs.append(False)
    cleanup_drop_collection("bnd_s07_ins")
    for c in list(req("POST", "collections+list", {})[1].get("data", [])):
        if c.startswith("bnd_s07_"):
            cleanup_drop_collection(c)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
