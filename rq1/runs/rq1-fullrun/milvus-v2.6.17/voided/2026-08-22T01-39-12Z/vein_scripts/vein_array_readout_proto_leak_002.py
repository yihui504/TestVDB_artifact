# vein: schema-declared Array field readout — proto wrapper leak vs dynamic-field plain array
# 对照组 A: dynamic field (undeclared, enableDynamicField) tags_dyn -> plain JSON list ["x"]
# 实验组:   schema-declared Array<VarChar> tags -> raw proto {"Data":{"StringData":{"data":[..]}}}
# Same endpoint (entities+query / entities+get / entities+search), same row, same writer.
# 源码定位: readout serialization path for declared Array fields re-serializes the
# schemapb.ArrayArray payload object instead of its data (internal/distributed/proxy/
# httpserver/utils.go array formatting path), unlike dynamic-field scalars.
import sys, os, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "debate_logs"))
from _lib import (safe_request, code_of, create_collection, load_collection,
                  drop_collection, query_all)

CLS = "v_arrleak_002"
verdict, detail = "NO_DEFECT", ""
try:
    drop_collection(CLS)
    s, b, raw = create_collection(CLS)
    if code_of(b) != 0:
        raise RuntimeError("create failed: " + raw)
    load_collection(CLS)
    # declared field tags; dynamic field tags_dyn via dynamic schema
    print("insert:", safe_request("POST", "entities+insert", {"collectionName": CLS, "data": [
        {"id": 1, "vector": [0.1] * 8, "tags": ["a", "b"], "tags_dyn": ["x", "y"]} ]})[2])
    time.sleep(1)

    for ep in ("entities+get",):
        g = safe_request("POST", ep, {"collectionName": CLS, "id": 1,
                                      "outputFields": ["tags", "tags_dyn"]})
        print(ep, g[2])
        rows = (g[1] or {}).get("data") or []
        if rows:
            declared = rows[0].get("tags")
            dyn = rows[0].get("tags_dyn")
            leaked = isinstance(declared, dict) and "Data" in declared
            plain = isinstance(dyn, list)
            if leaked and plain:
                verdict = "DEFECT_FOUND"
                detail = ("schema-declared Array field leaks proto wrapper %s while dynamic "
                          "array field returns plain JSON list %s on same endpoint/row" %
                          (json.dumps(declared), json.dumps(dyn)))
            elif leaked:
                print("NOTE: declared field leaks wrapper but dynamic field not a list:", dyn)
    q = query_all(CLS, output_fields=["tags", "tags_dyn"])
    print("query:", q[2])
    if verdict == "NO_DEFECT":
        rows = (q[1] or {}).get("data") or []
        if rows and isinstance(rows[0].get("tags"), dict) and "Data" in rows[0]["tags"] \
                and isinstance(rows[0].get("tags_dyn"), list):
            verdict = "DEFECT_FOUND"
            detail = ("query endpoint: declared Array leaks proto wrapper, dynamic array plain")
except Exception as e:
    verdict, detail = "SCRIPT_ERROR", str(e)
finally:
    try:
        drop_collection(CLS)
    except Exception:
        pass
print(detail)
print("VERDICT: %s" % verdict)
