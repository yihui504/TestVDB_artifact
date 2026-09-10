# boundary: collection name max length 255 + charset + field name rules
# Attack: string boundary (strategy 1/4)
# Constraints: milvus_range_collections_create_002 (name <=255),
#              milvus_type_field_name_rules_001 (field name rules)
# exploration_target: regression + novel
# Blindspot: BS-04
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, cleanup_drop_collection


def mkname(name, fname="vector"):
    cn = "bnd_s09_x"
    cleanup_drop_collection(cn)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": name,
        "schema": {"autoId": False, "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": fname, "dataType": "FloatVector",
             "elementTypeParams": {"dim": "4"}}]},
        "indexParams": [{"fieldName": fname, "indexName": "vi",
                         "metricType": "L2", "params": {"index_type": "AUTOINDEX"}}]})
    return is_ok(st, bd), raw


def main():
    rs = []
    for label, name, expect_ok in [
            ("name 255 chars", "n" * 255, True),
            ("name 256 chars", "n" * 256, False),
            ("name 1000 chars", "n" * 1000, False),
            ("name empty", "", False),
            ("name with space", "bad name", False),
            ("name starts digit", "9bad", False),
            ("name starts hyphen", "-bad", False),
            ("name NUL", "bad\x00name", False),
            ("name unicode 中文", "coll_中文", False),
            ("name $gt injection", "coll$(whoami)", False)]:
        ok, raw = mkname(name)
        print("CASE %-22s ok=%s | %s" % (label, ok, raw[:130]))
        if expect_ok and not ok:
            print("VERDICT_DEFECT 3 s09 %s rejected" % label); rs.append(False)
        if (not expect_ok) and ok:
            print("VERDICT_DEFECT 1 s09 %s accepted" % label); rs.append(False)
        cleanup_drop_collection(name if len(name) < 300 else "n" * 255)
    # field name rules (collection stays bnd_s09_x)
    for label, fname, expect_ok in [
            ("field 255 chars", "f" * 255, True),
            ("field 256 chars", "f" * 256, False),
            ("field starts digit", "9f", False),
            ("field with space", "bad f", False),
            ("field unicode", "field_中文", False)]:
        ok, raw = mkname("bnd_s09_x", fname=fname)
        print("CASE %-22s ok=%s | %s" % (label, ok, raw[:130]))
        if expect_ok and not ok:
            print("VERDICT_DEFECT 3 s09 %s rejected" % label); rs.append(False)
        if (not expect_ok) and ok:
            print("VERDICT_DEFECT 1 s09 %s accepted" % label); rs.append(False)
    cleanup_drop_collection("bnd_s09_x")
    for c in list(req("POST", "collections+list", {})[1].get("data", [])):
        if c.startswith("n" * 200) or c.startswith("bnd_s09") or c.startswith("f" * 200):
            cleanup_drop_collection(c)
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
