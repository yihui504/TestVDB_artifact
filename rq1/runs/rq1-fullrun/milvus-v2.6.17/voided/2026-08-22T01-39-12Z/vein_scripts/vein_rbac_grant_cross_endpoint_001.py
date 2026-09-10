# vein: RBAC OperatePrivilege-backed routes vs sibling RBAC routes — same param family, divergent behavior
# 对照组: users+create / roles+create / users+grant_role (all succeed code 0)
# 实验组: roles+grant_privilege / roles+grant_privilege_v2 (fail 65535 auth-md)
# 源码定位: internal/proxy/impl.go:5659 GetCurUserFromContext <- pkg/util/contextutil/context_util.go:98
#   <- internal/proxy/util.go:1452 NewContextWithMetadata only injects auth md when username != ""
#   <- internal/distributed/proxy/service.go:194 sets ContextUsername="" when AuthorizationEnabled=false
# Same deployment, same credentials (root:Milvus), same request shape -> only the
# OperatePrivilege handler chain requires ctx auth metadata the HTTP layer never provides.
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "debate_logs"))
import requests
from _lib import code_of

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
ROOT = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
R = "vrole_c1"; U = "vuser_c1"; PW = "Vpass001!x"
CLS = "v_ctrl_001"


def call(path, payload):
    r = requests.post(BASE + "/v2/vectordb/" + path.replace("+", "/"), headers=ROOT,
                      data=json.dumps(payload), timeout=30)
    return code_of(r.json()), r.text


verdict, detail = "NO_DEFECT", ""
try:
    # control group
    ctrl = []
    ctrl.append(("users+create", call("users+create", {"userName": U, "password": PW})))
    ctrl.append(("roles+create", call("roles+create", {"roleName": R})))
    ctrl.append(("users+grant_role", call("users+grant_role", {"userName": U, "roleName": R})))
    for n, (c, raw) in ctrl:
        print("CTRL %-18s -> %s %s" % (n, c, raw[:80]))

    # experiment group
    exp = []
    exp.append(("roles+grant_privilege", call("roles+grant_privilege",
               {"roleName": R, "objectType": "Global", "objectName": "*",
                "privilege": "CreateCollection", "dbName": "default"})))
    exp.append(("roles+grant_privilege_v2", call("roles+grant_privilege_v2",
               {"roleName": R, "privilege": "Query", "dbName": "default", "collectionName": "*"})))
    for n, (c, raw) in exp:
        print("EXP  %-22s -> %s %s" % (n, c, raw[:100]))

    ctrl_ok = all(c == 0 for _, (c, _) in ctrl)
    exp_all_65535 = all(c == 65535 and "authorization from the md" in raw
                        for _, (c, raw) in exp)
    if ctrl_ok and exp_all_65535:
        verdict = "DEFECT_FOUND"
        detail = ("cross-endpoint divergence: control RBAC endpoints all code 0 while both "
                  "OperatePrivilege routes fail 65535 'fail to get authorization from the md' "
                  "for root; source: NewContextWithMetadata skips auth md when username=='' "
                  "(proxy/util.go:1452) but OperatePrivilege (impl.go:5659) unconditionally "
                  "requires it")
    elif not ctrl_ok:
        verdict, detail = "SCRIPT_ERROR", "control group failed"
except Exception as e:
    verdict, detail = "SCRIPT_ERROR", str(e)
finally:
    try:
        call("users+revoke_role", {"userName": U, "roleName": R})
        call("users+drop", {"userName": U})
        call("roles+drop", {"roleName": R})
    except Exception:
        pass
print(detail)
print("VERDICT: %s" % verdict)
