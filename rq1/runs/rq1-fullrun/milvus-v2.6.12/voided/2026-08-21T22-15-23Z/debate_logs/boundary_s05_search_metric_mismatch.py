# boundary: search metric_type vs collection metric consistency
# Attack: semantic boundary (strategy 4)
# Constraint: contract entities+search — metricType is a TOP-LEVEL SearchReqV2 field (not in params;
#             params holds float fields like radius/range_filter). Mismatch with collection metric should error.
# exploration_target: novel
# Blindspot: BS-01
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, create_float_collection, cleanup_drop_collection

CN = "bnd_s05_metric"


def case(label, extra, expect_err):
    p = {"collectionName": CN, "data": [[0.1] * 8], "limit": 3}
    p.update(extra)
    st, bd, raw = req("POST", "entities+search", p)
    ok = is_ok(st, bd)
    print("CASE %-24s status=%s ok=%s | %s" % (label, st, ok, raw[:150]))
    if expect_err and ok:
        print("VERDICT_DEFECT 1 s05 %s accepted" % label)
        return False
    if not expect_err and not ok:
        print("VERDICT_DEFECT 3 s05 %s rejected" % label)
        return False
    return True


def main():
    ok1, err = create_float_collection(CN, dim=8, metric="L2")
    if not ok1:
        print("SETUP_FAIL s05 %s" % err); print("VERDICT_SCRIPT_ERROR"); return
    req("POST", "entities+insert", {"collectionName": CN, "data": [{"id": 1, "vector": [0.1] * 8}]})
    rs = []
    rs.append(case("no metric (default)", {}, expect_err=False))
    rs.append(case("matching L2", {"metricType": "L2"}, expect_err=False))
    rs.append(case("diff IP", {"metricType": "IP"}, expect_err=True))
    rs.append(case("diff COSINE", {"metricType": "COSINE"}, expect_err=True))
    rs.append(case("bogus METRIC", {"metricType": "BOGUS"}, expect_err=True))
    rs.append(case("lowercase l2", {"metricType": "l2"}, expect_err=False))
    rs.append(case("int metric", {"metricType": 42}, expect_err=True))
    cleanup_drop_collection(CN)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
