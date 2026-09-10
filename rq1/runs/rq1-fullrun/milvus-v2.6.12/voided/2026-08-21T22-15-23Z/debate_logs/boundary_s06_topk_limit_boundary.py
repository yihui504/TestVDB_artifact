# boundary: topK limit boundary — limit+offset in [1,16384]
# Attack: numeric boundary (strategy 1)
# Constraint: milvus_range_entities_search_001; milvus_range_entities_search_002 (default 100)
# exploration_target: regression + novel
# Blindspot: BS-04
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, create_float_collection, cleanup_drop_collection

CN = "bnd_s06_topk"


def case(label, extra, expect_err):
    p = {"collectionName": CN, "data": [[0.1] * 8]}
    p.update(extra)
    st, bd, raw = req("POST", "entities+search", p)
    ok = is_ok(st, bd)
    print("CASE %-30s status=%s ok=%s | %s" % (label, st, ok, raw[:150]))
    if expect_err and ok:
        print("VERDICT_DEFECT 1 s06 %s accepted" % label)
        return False
    if not expect_err and not ok:
        print("VERDICT_DEFECT 3 s06 %s rejected" % label)
        return False
    return True


def main():
    ok1, err = create_float_collection(CN, dim=8)
    if not ok1:
        print("SETUP_FAIL s06 %s" % err); print("VERDICT_SCRIPT_ERROR"); return
    req("POST", "entities+insert", {"collectionName": CN, "data": [{"id": 1, "vector": [0.1] * 8}]})
    rs = []
    rs.append(case("limit=1 (min)", {"limit": 1}, False))
    rs.append(case("limit=0", {"limit": 0}, True))
    rs.append(case("limit=-1", {"limit": -1}, True))
    rs.append(case("limit=16383", {"limit": 16383}, False))   # returns 1 hit, fine
    rs.append(case("limit=16384 (max)", {"limit": 16384}, False))
    rs.append(case("limit=16385 (max+1)", {"limit": 16385}, True))
    rs.append(case("limit=1e9", {"limit": 1000000000}, True))
    rs.append(case("offset=-1 limit=1", {"limit": 1, "offset": -1}, True))
    rs.append(case("limit=16384 offset=1", {"limit": 16384, "offset": 1}, True))  # sum 16385
    rs.append(case("limit as str '5'", {"limit": "5"}, True))  # strict JSON typing: no coercion
    rs.append(case("limit float 5.5", {"limit": 5.5}, True))
    rs.append(case("limit null", {"limit": None}, False))
    cleanup_drop_collection(CN)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
