# boundary: quick mode vs full schema mode conflict
# Attack: type boundary (strategy 2)
# Constraint: milvus_type_collections_create_003 — conflict -> code 1100
# exploration_target: regression + novel
# Blindspot: BS-01
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, cleanup_drop_collection

SCHEMA = {"autoId": False, "fields": [
    {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
    {"fieldName": "vector", "dataType": "FloatVector", "elementTypeParams": {"dim": "4"}}]}
IDX = [{"fieldName": "vector", "indexName": "vi", "metricType": "L2",
        "params": {"index_type": "AUTOINDEX"}}]


def case(label, body, expect_ok):
    cn = body.get("collectionName", "bnd_s10_x")
    cleanup_drop_collection(cn)
    st, bd, raw = req("POST", "collections+create", body)
    ok = is_ok(st, bd)
    print("CASE %-30s ok=%s | %s" % (label, ok, raw[:140]))
    if expect_ok and not ok:
        print("VERDICT_DEFECT 3 s10 %s rejected" % label); return False
    if (not expect_ok) and ok:
        print("VERDICT_DEFECT 1 s10 %s accepted" % label); return False
    return True


def main():
    rs = []
    rs.append(case("quick only (dim)",
                   {"collectionName": "bnd_s10_a", "dimension": 4}, True))
    rs.append(case("full only (schema)",
                   {"collectionName": "bnd_s10_b", "schema": SCHEMA,
                    "indexParams": IDX}, True))
    rs.append(case("BOTH schema+dimension",
                   {"collectionName": "bnd_s10_c", "schema": SCHEMA,
                    "indexParams": IDX, "dimension": 4}, False))
    rs.append(case("quick + idDataType",
                   {"collectionName": "bnd_s10_d", "dimension": 4,
                    "idDataType": "VarChar"}, True))
    rs.append(case("full + idDataType conflict",
                   {"collectionName": "bnd_s10_e", "schema": SCHEMA,
                    "indexParams": IDX, "idDataType": "VarChar"}, False))
    rs.append(case("quick + metricType",
                   {"collectionName": "bnd_s10_f", "dimension": 4,
                    "metricType": "COSINE"}, True))
    rs.append(case("quick dim=0",
                   {"collectionName": "bnd_s10_g", "dimension": 0}, False))
    rs.append(case("quick dim=-4",
                   {"collectionName": "bnd_s10_h", "dimension": -4}, False))
    rs.append(case("quick dim as str '4'",
                   {"collectionName": "bnd_s10_i", "dimension": "4"}, False))  # strict typing
    rs.append(case("no schema no dim",
                   {"collectionName": "bnd_s10_j"}, False))
    for c in "abcdefghij":
        cleanup_drop_collection("bnd_s10_" + c)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
