# boundary: schema.fields[].dataType enum + BinaryVector dim multiple-of-8 + Array elementDataType
# Attack: type boundary (strategy 2)
# Constraints: milvus_type_collections_create_001 (dataType enum),
#              milvus_type_collections_create_005 (BinaryVector dim %8),
#              milvus_type_collections_create_006 (Array requires elementDataType)
# exploration_target: regression + novel
# Blindspot: BS-01
# Fixture note: every schema needs a FloatVector field + index; BinaryVector index uses JACCARD.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, cleanup_drop_collection


def mk(name, fields, metric="L2"):
    cleanup_drop_collection(name)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": name, "schema": {"autoId": False, "fields": fields},
        "indexParams": [{"fieldName": "vector", "indexName": "vi",
                         "metricType": metric, "params": {"index_type": "AUTOINDEX"}}]})
    return is_ok(st, bd), raw


def case(n, label, fields, expect_ok, metric="L2"):
    ok, raw = mk("bnd_s08_%d" % n, fields, metric)
    print("CASE %-34s ok=%s | %s" % (label, ok, raw[:130]))
    if expect_ok and not ok:
        print("VERDICT_DEFECT 3 s08 %s rejected" % label); return False
    if (not expect_ok) and ok:
        print("VERDICT_DEFECT 1 s08 %s accepted" % label); return False
    return True


def main():
    pk = {"fieldName": "id", "dataType": "Int64", "isPrimary": True}
    fvec = {"fieldName": "vector", "dataType": "FloatVector",
            "elementTypeParams": {"dim": "8"}}
    rs = []
    n = 0
    # valid enum values (scalar tested as an extra field alongside a FloatVector)
    for dt, extra in [("Int64", None), ("VarChar", {"max_length": "64"}), ("Bool", None),
                      ("Int8", None), ("Float16Vector", None)]:
        n += 1
        f = {"fieldName": "extra_%d" % n, "dataType": dt}
        if extra:
            f["elementTypeParams"] = extra
        if dt == "Float16Vector":
            rs.append(case(n, "valid dataType %s" % dt,
                           [pk, {"fieldName": "vector", "dataType": dt,
                                 "elementTypeParams": {"dim": "8"}}], True))
        else:
            rs.append(case(n, "valid dataType %s" % dt, [pk, fvec, f], True))
    # invalid enum variants on vector field
    for label, dt in [("bogus FloatVectr", "FloatVectr"), ("lowercase floatvector", "floatvector"),
                      ("null dataType", None)]:
        n += 1
        rs.append(case(n, label, [pk, {"fieldName": "vector", "dataType": dt,
                                       "elementTypeParams": {"dim": "8"}}], False))
    n += 1
    rs.append(case(n, "dataType 42", [pk, {"fieldName": "vector", "dataType": 42,
                                           "elementTypeParams": {"dim": "8"}}], False))
    # BinaryVector dim multiple of 8 (JACCARD metric)
    for label, dim, expect in [("BinaryVector dim=8", "8", True),
                               ("BinaryVector dim=9 (not %8)", "9", False),
                               ("BinaryVector dim=16", "16", True),
                               ("BinaryVector dim=0", "0", False)]:
        n += 1
        rs.append(case(n, label, [pk, {"fieldName": "vector", "dataType": "BinaryVector",
                                       "elementTypeParams": {"dim": dim}}], expect, metric="JACCARD"))
    # Array requires elementDataType
    n += 1
    rs.append(case(n, "Array w/o elementDataType",
                   [pk, fvec, {"fieldName": "arr", "dataType": "Array"}], False))
    n += 1
    rs.append(case(n, "Array with bogus elementDataType",
                   [pk, fvec, {"fieldName": "arr", "dataType": "Array",
                               "elementDataType": "BogusType"}], False))
    n += 1
    rs.append(case(n, "Array with valid elementDataType",
                   [pk, fvec, {"fieldName": "arr", "dataType": "Array",
                               "elementDataType": "Int64",
                               "elementTypeParams": {"max_capacity": "64"}}], True))
    # required-field checks (extra field missing fieldName / dataType)
    n += 1
    rs.append(case(n, "extra field missing fieldName", [pk, fvec, {"dataType": "Int64"}], False))
    n += 1
    rs.append(case(n, "extra field missing dataType", [pk, fvec, {"fieldName": "x"}], False))
    for c in list(req("POST", "collections+list", {})[1].get("data", [])):
        if c.startswith("bnd_s08_"):
            cleanup_drop_collection(c)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
