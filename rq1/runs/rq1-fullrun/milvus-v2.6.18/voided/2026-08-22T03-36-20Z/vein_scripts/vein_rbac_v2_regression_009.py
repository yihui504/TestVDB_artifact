# script_id: vein_rbac_v2_regression_009
# Attack: vein strategy grant_privilege_v2 regression check + source-located defect: RBAC grant/revoke
# endpoints unusable over REST when authorizationEnabled=false (HTTP credential never propagated to gRPC ctx)
"""
Source-located (vein) defect chain on v2.6.18, authorizationEnabled=false (default standalone config):
 1. service.go:authenticate() only mounted when AuthorizationEnabled=true -> gin ctx ContextUsername="",
    ContextToken never set.
 2. handler_v2.go wrapperProxy: token forwarding is conditional on ginCtx.Get(ContextToken) (always absent).
 3. proxy/impl.go OperatePrivilegeV2 (line 5622): GetCurUserFromContext(ctx) unconditionally required ->
    "fail to get authorization from the md, authorization:[token]" code 65535.
Net effect: roles+grant_privilege_v2 / revoke_privilege_v2 / grant_privilege(v1 with correct shapes) are
IMPOSSIBLE to call successfully over REST in the default standalone deployment, while roles create/drop/describe
succeed. Also verified: enabling common/authorizationEnabled via etcd at runtime does NOT mount the middleware
(checked at startup only) -> no runtime remedy without restart.
This is a state-consistency defect: role management surface is split-usable (role lifecycle works, privilege
lifecycle cannot work).
"""
import sys
sys.path.insert(0, r"<HOME>\.claude\plugins\cache\testvdb\testvdb\2.3.0\results\milvus\v2.6.18\2026-08-22T03-36-20Z\debate_logs")
from _milvus_helper import safe_request, code

ROLE = "vn_role_009"
VERDICT = "SCRIPT_ERROR"
try:
    try:
        safe_request("POST", "roles+drop", {"roleName": ROLE})
    except Exception:
        pass
    s, b, raw = safe_request("POST", "roles+create", {"roleName": ROLE})
    print("role create:", s, raw[:150])
    if code(b) != 0:
        print("RBAC create unavailable -> SCRIPT_ERROR surface"); VERDICT = "SCRIPT_ERROR"; sys.exit(0)

    # correct GrantV2Req shape per request_v2.go:519 (roleName, dbName, collectionName, privilege)
    g2 = {"roleName": ROLE, "privilege": "CollectionList", "dbName": "default", "collectionName": "*"}
    s, b, raw = safe_request("POST", "roles+grant_privilege_v2", g2)
    print("grant_privilege_v2 (correct shape):", s, raw[:220])
    v2_err = code(b) != 0

    # v1 GrantReq shape (roleName, objectType, objectName, privilege[, dbName])
    g1 = {"roleName": ROLE, "objectType": "Global", "objectName": "*", "privilege": "CreateCollection"}
    s, b, raw = safe_request("POST", "roles+grant_privilege", g1)
    print("grant_privilege (v1 shape):", s, raw[:220])
    v1_err = code(b) != 0

    # role lifecycle works in same deployment?
    s, b, raw = safe_request("POST", "roles+describe", {"roleName": ROLE})
    print("describe:", s, raw[:150])
    desc_ok = code(b) == 0
    s, b, raw = safe_request("POST", "roles+drop", {"roleName": ROLE})
    print("drop:", s, raw[:120])
    drop_ok = code(b) == 0
    s, b, raw = safe_request("POST", "roles+list", {})
    names = (b or {}).get("data") or []
    zombie = ROLE in names
    print("roles list contains role after drop:", zombie)

    auth_lost = ("fail to get authorization" in raw) or v2_err  # marker set below
    # re-fetch raw error text for classification
    s2, b2, raw2 = safe_request("POST", "roles+grant_privilege_v2", g2)
    cred_lost = "authorization" in raw2 and code(b2) == 65535

    if v2_err and v1_err and desc_ok and drop_ok and cred_lost:
        print("DEFECT: privilege grant/revoke unusable over REST (code 65535 credential propagation gap) "
              "while role lifecycle works in same deployment (Type4 state-consistency, source: "
              "proxy/impl.go:5622 + service.go:130 + handler_v2.go:516-527)")
        VERDICT = "DEFECT_FOUND"; sys.exit(1)
    if zombie:
        print("DEFECT: zombie role after drop"); VERDICT = "DEFECT_FOUND"; sys.exit(1)
    print("no defect on this surface")
    VERDICT = "NO_DEFECT"
except SystemExit:
    raise
except Exception as e:
    print("EXC:", repr(e)); VERDICT = "SCRIPT_ERROR"
finally:
    try:
        safe_request("POST", "roles+drop", {"roleName": ROLE})
    except Exception:
        pass
    print("VERDICT: %s" % VERDICT)
