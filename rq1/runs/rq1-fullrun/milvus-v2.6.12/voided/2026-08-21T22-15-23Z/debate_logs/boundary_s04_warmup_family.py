# boundary: warmup property family (NEW v2.6.12)
# Attack: schema-field invalid values + silent-drop detection (strategy 2 / judge_schema_attack-style)
# Constraint: milvus_type_collections_create_007 (warmup.* keys, enum 'disable'|'sync')
#             milvus_type_collections_create_008 (KNOWN GAP: bare 'warmup' key unvalidated)
# exploration_target: regression + novel
# Blindspot: BS-04 Boundary Default Optimism
# Live-confirmed shape: the real API is FLAT keys in params: "warmup.vectorIndex": "sync"
# (persists to describe properties). Enum is lowercase {'disable','sync'}.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boundary_common import req, is_ok, cleanup_drop_collection

KEYS = ["scalarField", "scalarIndex", "vectorField", "vectorIndex"]


def mk(name, params):
    cleanup_drop_collection(name)
    st, bd, raw = req("POST", "collections+create", {
        "collectionName": name,
        "schema": {"autoId": False, "fields": [
            {"fieldName": "id", "dataType": "Int64", "isPrimary": True},
            {"fieldName": "vector", "dataType": "FloatVector",
             "elementTypeParams": {"dim": "4"}}]},
        "indexParams": [{"fieldName": "vector", "indexName": "vi",
                         "metricType": "L2", "params": {"index_type": "AUTOINDEX"}}],
        "params": params})
    return st, bd, raw


def props_of(name):
    st, bd, _ = req("POST", "collections+describe", {"collectionName": name})
    if not isinstance(bd, dict):
        return {}
    return {p.get("key"): p.get("value") for p in bd.get("data", {}).get("properties", [])}


def case(name, label, params, expect_reject):
    st, bd, raw = mk(name, params)
    ok = is_ok(st, bd)
    defect = False
    if expect_reject:
        if ok:
            # accepted an invalid value -> only a defect if it also persisted (Type1) or dropped (silent)
            pv = props_of(name)
            warm = {k: v for k, v in pv.items() if k.startswith("warmup")}
            print("CASE %-34s ACCEPTED(illegal) persisted_warmup=%s | %s" % (label, warm, raw[:100]))
            if warm:
                print("VERDICT_DEFECT 1 s04 %s invalid value ACCEPTED+PERSISTED" % label)
                defect = True
            else:
                print("VERDICT_DEFECT 4 s04 %s invalid value accepted then silently dropped" % label)
                defect = True
        else:
            print("CASE %-34s rejected: %s" % (label, raw[:130]))
    else:
        if not ok:
            print("VERDICT_DEFECT 3 s04 %s valid value rejected: %s" % (label, raw[:130]))
            defect = True
        else:
            pv = props_of(name)
            warm = {k: v for k, v in pv.items() if k.startswith("warmup")}
            print("CASE %-34s ok persisted_warmup=%s" % (label, warm))
            if not warm:
                print("VERDICT_DEFECT 4 s04 %s valid value silently dropped" % label)
                defect = True
    cleanup_drop_collection(name)
    return not defect


def main():
    rs = []
    n = 0
    # enum matrix per key: lowercase sync/disable valid; uppercase/BOGUS/int/case-variant invalid
    for k in KEYS:
        for val, expect_reject in [("sync", False), ("disable", False),
                                   ("SYNC", True), ("DISABLED", True), ("BOGUS", True), (42, True)]:
            n += 1
            rs.append(case("bnd_s04_%d" % n, "flat warmup.%s=%r" % (k, val),
                           {"warmup.%s" % k: val}, expect_reject))
    # KNOWN GAP regression: bare 'warmup' key (object or string) — invalid contents must still be rejected
    n += 1
    rs.append(case("bnd_s04_%d" % n, "bare warmup=BOGUS(str)", {"warmup": "BOGUS"}, True))
    n += 1
    rs.append(case("bnd_s04_%d" % n, "bare warmup={vectorIndex:BOGUS}",
                   {"warmup": {"vectorIndex": "BOGUS"}}, True))
    n += 1
    rs.append(case("bnd_s04_%d" % n, "bare warmup={vectorIndex:sync} (nested form)",
                   {"warmup": {"vectorIndex": "sync"}}, True))
    print("VERDICT_DEFECT_FOUND" if any(not r for r in rs) else "VERDICT_NO_DEFECT")


if __name__ == "__main__":
    main()
