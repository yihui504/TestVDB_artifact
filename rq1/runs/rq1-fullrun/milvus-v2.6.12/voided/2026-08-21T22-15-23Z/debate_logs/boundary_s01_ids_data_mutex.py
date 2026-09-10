# boundary: search ids/data mutual-exclusion matrix
# Attack: type boundary (strategy 2)
# Constraint: milvus_type_entities_search_002 — exactly one of ids or data must be provided
# exploration_target: regression
# Blindspot: BS-01 Parameter Coercion Trust
"""
VERDICT conventions (VERDICT_* markers only)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, create_float_collection, cleanup_drop_collection

CN = "bnd_s01_mutex"


def matrix_case(label, payload, expect_err):
    st, bd, raw = req("POST", "entities+search", payload)
    ok = is_ok(st, bd)
    code = bd.get("code") if isinstance(bd, dict) else None
    print("CASE %-12s status=%s code=%s ok=%s | %s" % (label, st, code, ok, raw[:160]))
    if expect_err and ok:
        print("VERDICT_DEFECT 1 s01 both-accepted %s code=0" % label)
        return False
    if not expect_err and not ok:
        print("VERDICT_DEFECT 3 s01 legit-search-rejected %s" % label)
        return False
    return True


def main():
    ok1, err = create_float_collection(CN, dim=8)
    if not ok1:
        print("SETUP_FAIL s01 %s" % err)
        print("VERDICT_SCRIPT_ERROR")
        return
    req("POST", "entities+insert", {"collectionName": CN, "data": [
        {"id": 1, "vector": [0.1] * 8}]})
    qv = [0.1] * 8
    base = {"collectionName": CN, "limit": 3}
    results = []
    # 1) BOTH ids+data
    p = dict(base); p["data"] = [qv]; p["ids"] = [1, 2]
    results.append(matrix_case("both", p, expect_err=True))
    # 2) NEITHER ids nor data
    p = dict(base)
    results.append(matrix_case("neither", p, expect_err=True))
    # 3) ids:[] empty list
    p = dict(base); p["ids"] = []
    results.append(matrix_case("ids_empty", p, expect_err=True))
    # 4) ids valid only (sanity, should succeed)
    p = dict(base); p["ids"] = [1]
    results.append(matrix_case("ids_ok", p, expect_err=False))
    # 5) data valid only (sanity)
    p = dict(base); p["data"] = [qv]
    results.append(matrix_case("data_ok", p, expect_err=False))
    cleanup_drop_collection(CN)
    if any(not r for r in results):
        print("VERDICT_DEFECT_FOUND")
    else:
        print("VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
