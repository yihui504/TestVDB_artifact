# boundary: ids type-conversion rules (convertIDsToSchemapbIDs)
# Attack: type boundary (strategy 2)
# Constraint: milvus_type_entities_search_003 — int64 pk fractional id -> 1100; VarChar empty id -> error;
#             unsupported pk DataType / mixed / bool / null ids -> reject
# exploration_target: regression + novel
# Blindspot: BS-01 Parameter Coercion Trust
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, create_float_collection, cleanup_drop_collection

CN = "bnd_s02_ids"


def case(label, ids, expect_err=True):
    st, bd, raw = req("POST", "entities+search",
                      {"collectionName": CN, "ids": ids, "limit": 3, "outputFields": ["id"]})
    ok = is_ok(st, bd)
    print("CASE %-14s status=%s ok=%s | %s" % (label, st, ok, raw[:170]))
    if expect_err and ok:
        print("VERDICT_DEFECT 1 s02 %s accepted code=0" % label)
        return False
    if not expect_err and not ok:
        print("VERDICT_DEFECT 3 s02 %s rejected" % label)
        return False
    return True


def main():
    ok1, err = create_float_collection(CN, dim=8)
    if not ok1:
        print("SETUP_FAIL s02 %s" % err); print("VERDICT_SCRIPT_ERROR"); return
    req("POST", "entities+insert", {"collectionName": CN, "data": [{"id": 1, "vector": [0.1] * 8}]})
    rs = []
    rs.append(case("frac_int_id", [1.5]))            # regression: fractional int64 pk -> 1100
    rs.append(case("int_as_str", ["1"], expect_err=False))   # documented coercion: numeric string -> int64
    rs.append(case("bool_id", [True]))               # novel: bool
    rs.append(case("null_in_ids", [None]))           # novel: null element
    rs.append(case("mixed", [1, "abc"]))             # novel: mixed types
    rs.append(case("nested_arr", [[1, 2]]))          # novel: nested array
    rs.append(case("ids_not_array", 1))              # novel: scalar instead of array
    rs.append(case("valid", [1], expect_err=False))  # sanity
    cleanup_drop_collection(CN)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
