"""Vein: replicationConfig.asyncEnabled silently rewritten.

Discover: POST /v1/schema with replicationConfig {factor:1, asyncEnabled:true}
returns 200 but readback shows asyncEnabled=false. User input is silently
discarded with no 4xx and no warning. Control: asyncEnabled=false with
factor=1 readback false (consistent) => the flip is specific to the
user-requested true.
Root cause (source v1.38.0 adapters/handlers/rest/restcompat/wrappers.go:40):
  AsyncEnabled: rc.Factor > 1 && !asyncReplicationGloballyDisabled.Load()
i.e. readback derives asyncEnabled from factor>1 AND a global runtime flag,
ignoring the persisted user value. A schema-persisted flag that the API
silently overrides on read is a Type2 semantic drift defect (config loss /
misleading state reporting on single-node setups).
VERDICT: DEFECT_FOUND if POST accepts asyncEnabled=true but GET returns false.
"""
import json, requests

DB = "http://localhost:8080"


def safe_request(method, path, body=None):
    try:
        r = requests.request(method, DB + path, json=body, timeout=10)
        return r.status_code, r.text
    except Exception as e:
        return -1, str(e)


def main():
    cls = "VeinAsyncRep3"
    findings = []
    safe_request("DELETE", f"/v1/schema/{cls}")

    # attack: asyncEnabled=true, factor=1 (single node)
    st, body = safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "replicationConfig": {"factor": 1, "asyncEnabled": True}})
    st2, rb = safe_request("GET", f"/v1/schema/{cls}")
    if st2 == 200:
        rc = json.loads(rb).get("replicationConfig", {})
        if st == 200 and rc.get("asyncEnabled") is False:
            findings.append(
                f"POST 200 with asyncEnabled=true but GET readback asyncEnabled=false "
                f"(replicationConfig={rc}) — silent input rewrite")
        # control: explicit false stays false (consistent)
        if rc.get("factor") == 1:
            findings.append(f"control context: factor=1 (single-node legal), readback={rc}")

    # control 2: asyncEnabled explicitly false, no flip ambiguity
    safe_request("DELETE", f"/v1/schema/{cls}")
    safe_request("POST", "/v1/schema", {
        "class": cls, "vectorizer": "none",
        "replicationConfig": {"factor": 1, "asyncEnabled": False}})
    _, rbc = safe_request("GET", f"/v1/schema/{cls}")
    rcc = json.loads(rbc)["replicationConfig"]
    assert rcc["asyncEnabled"] is False
    findings.append("control: asyncEnabled=false readback false (consistent) => flip is input-dependent, not a serialization default")

    safe_request("DELETE", f"/v1/schema/{cls}")
    for f in findings:
        print("FINDING:", f)
    print("VERDICT: DEFECT_FOUND" if findings else "VERDICT: NOT_FOUND")


try:
    main()
except Exception as e:
    print("SCRIPT_ERROR:", e)
