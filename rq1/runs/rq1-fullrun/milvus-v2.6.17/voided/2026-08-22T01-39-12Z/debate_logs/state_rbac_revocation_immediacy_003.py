# state: RBAC privilege grant/revoke over REST — granted revocation immediacy test
# Attack: strategy 2 (post-change consistency) x roles+grant_privilege / roles+revoke_privilege
# FINDING (milvus v2.6.17, auth disabled deployment): roles+grant_privilege and
# roles+grant_privilege_v2 (and revoke counterparts) ALWAYS return
# code 65535 "fail to get authorization from the md, authorization:[token]" even for root.
# Root cause chain (source-verified):
#   service.go: auth middleware only registered when CommonCfg.AuthorizationEnabled;
#   when disabled, ContextUsername stays "" (service.go:194) ->
#   wrapperPost calls NewContextWithMetadata(username="") which appends NO authorization md
#   (internal/proxy/util.go:1452-1462 only appends auth md if username != "") ->
#   Proxy.OperatePrivilege -> GetCurUserFromContext -> GetAuthInfoFromContext fails
#   (impl.go:5659, context_util.go:98).
# Inconsistency: sibling RBAC endpoints (users+create/drop, roles+create/drop/describe,
# users+grant_role) all succeed code 0 in the same deployment; only OperatePrivilege-backed
# routes demand ctx auth metadata that the HTTP layer never injects when auth is off.
# Consequence: roles can be created but NEVER granted any privilege via REST when
# authorization is disabled => RBAC unusable/deferred-failure state inconsistency.
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from _lib import code_of

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530").rstrip("/")
ROOT = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
R = "strole_003"


def call(path, payload):
    r = requests.post(BASE + "/v2/vectordb/" + path.replace("+", "/"), headers=ROOT,
                      data=json.dumps(payload), timeout=30)
    try:
        return code_of(r.json()), r.text
    except Exception:
        return None, r.text


verdict, detail = "NO_DEFECT", ""
try:
    call("roles+drop", {"roleName": R})
    c0, raw0 = call("roles+create", {"roleName": R})
    print("roles+create:", c0, raw0[:100])
    c1, raw1 = call("roles+grant_privilege", {"roleName": R, "objectType": "Global",
                                              "objectName": "*", "privilege": "CreateCollection",
                                              "dbName": "default"})
    print("roles+grant_privilege:", c1, raw1[:160])
    c2, raw2 = call("roles+describe", {"roleName": R})
    print("roles+describe:", c2, raw2[:160])
    granted = bool(((json.loads(raw2) if raw2.startswith("{") else {}).get("data")))
    if (c0 == 0) and (c1 == 65535) and "authorization from the md" in raw1:
        # role created but cannot be granted privileges although caller is root
        verdict = "DEFECT_FOUND"
        detail = ("roles+grant_privilege fails 65535 'fail to get authorization from the md' for "
                  "root while sibling RBAC endpoints (roles+create code %d) succeed; role is left "
                  "in a privilege-less zombie state (describe grants: %s)" % (c0, raw2[:80]))
except Exception as e:
    verdict, detail = "SCRIPT_ERROR", str(e)
finally:
    try:
        call("roles+drop", {"roleName": R})
    except Exception:
        pass
print(detail)
print("VERDICT: %s" % verdict)
