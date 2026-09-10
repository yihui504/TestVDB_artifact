# boundary: VarChar pk ids — empty string id and whitespace/control-char ids
# Attack: type + special value boundary (strategies 2/4)
# Constraint: milvus_type_entities_search_003 — VarChar empty string id -> error
# exploration_target: regression + novel (whitespace, NUL, unicode, lone surrogate)
# Blindspot: BS-01
# Note: search-by-ids for nonexistent ids -> code 1100 "IDs do not exist" (recorded, judge call),
# so sanity cases must insert the id first.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, cleanup_drop_collection

CN = "bnd_s03_vc"
UID = "id_中文_🎯"


def case(label, ids, expect_err=True):
    st, bd, raw = req("POST", "entities+search",
                      {"collectionName": CN, "ids": ids, "limit": 3})
    ok = is_ok(st, bd)
    print("CASE %-16s status=%s ok=%s | %s" % (label, st, ok, raw[:170]))
    if expect_err and ok:
        print("VERDICT_DEFECT 1 s03 %s accepted code=0" % label)
        return False
    if not expect_err and not ok:
        print("VERDICT_DEFECT 3 s03 %s rejected" % label)
        return False
    return True


def main():
    cleanup_drop_collection(CN)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": CN,
        "schema": {"autoId": False, "fields": [
            {"fieldName": "id", "dataType": "VarChar", "isPrimary": True,
             "elementTypeParams": {"max_length": "64"}},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "4"}}]},
        "indexParams": [{"fieldName": "vector", "indexName": "vi",
                         "metricType": "L2", "params": {"index_type": "AUTOINDEX"}}]})
    if not is_ok(st, bd):
        print("SETUP_FAIL s03 %s" % raw); print("VERDICT_SCRIPT_ERROR"); return
    req("POST", "collections+load", {"collectionName": CN})
    rst, rbd, rraw = req("POST", "entities+insert", {"collectionName": CN,
                                                     "data": [{"id": UID, "vector": [0.1] * 4}]})
    print("SETUP insert unicode id ok=%s | %s" % (is_ok(rst, rbd), rraw[:120]))
    rs = []
    rs.append(case("empty_str_id", [""]))            # regression per contract
    rs.append(case("space_id", [" "]))               # novel: whitespace-only id
    rs.append(case("nul_id", ["a\x00b"]))            # novel: NUL in id
    rs.append(case("unicode_id", [UID], expect_err=False))  # inserted id must be searchable
    # lone surrogate via raw bytes body
    raw_body = ('{"collectionName":"%s","ids":["%s"],"limit":3}' % (CN, "\\ud800")).encode()
    st, bd, r2 = req("POST", "entities+search", raw_data=raw_body)
    print("CASE lone_surrogate status=%s ok=%s | %s" % (st, is_ok(st, bd), r2[:170]))
    if is_ok(st, bd):
        print("VERDICT_DEFECT 1 s03 lone_surrogate accepted")
        rs.append(False)
    cleanup_drop_collection(CN)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
