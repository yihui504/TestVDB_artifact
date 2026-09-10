# boundary: search consistencyLevel enum
# Attack: type boundary (strategy 2)
# Constraint: milvus_type_entities_search_001 — invalid -> code 1100
# exploration_target: regression + novel
# Blindspot: BS-01
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, create_float_collection, cleanup_drop_collection

CN = "bnd_s11_cl"


def case(label, cl, expect_err):
    st, bd, raw = req("POST", "entities+search",
                      {"collectionName": CN, "data": [[0.1] * 8], "limit": 3,
                       "consistencyLevel": cl})
    ok = is_ok(st, bd)
    print("CASE %-26s status=%s ok=%s | %s" % (label, st, ok, raw[:140]))
    if expect_err and ok:
        print("VERDICT_DEFECT 1 s11 %s accepted" % label)
        return False
    if not expect_err and not ok:
        print("VERDICT_DEFECT 3 s11 %s rejected" % label)
        return False
    return True


def main():
    ok1, err = create_float_collection(CN, dim=8)
    if not ok1:
        print("SETUP_FAIL s11 %s" % err); print("VERDICT_SCRIPT_ERROR"); return
    req("POST", "entities+insert", {"collectionName": CN, "data": [{"id": 1, "vector": [0.1] * 8}]})
    rs = []
    for cl in ["Strong", "Bounded", "Eventually", "Session"]:
        rs.append(case("valid %s" % cl, cl, False))
    rs.append(case("bogus WEAK", "WEAK", True))
    rs.append(case("lowercase strong", "strong", True))
    rs.append(case("empty string", "", True))
    rs.append(case("int 3", 3, True))
    rs.append(case("null", None, False))
    rs.append(case("list", ["Strong"], True))
    cleanup_drop_collection(CN)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
