"""Vein: PUT /v1/schema/{c}/shards/{s} echoes request body verbatim on invalid status.

Discover: with status="NOT_A_STATUS" on a NONEXISTENT shard the API returns
200 echoing the invalid body (no shard existence check, no validation).
On a real shard the same input correctly returns 422
("invalid storage status"). Handler:
.weaviate-src-1381/adapters/handlers/rest/handlers_schema.go:431
updateShardStatus returns params.Body directly; validation happens in
Shard.updateStatusUnlocked (adapters/repos/db/shard_status.go:102 ->
storagestate.ValidateStatus) which is only reached if the shard resolves.
Nonexistent-shard path appears to no-op through raft apply without error.
"""
import json
import urllib.request

BASE = "http://localhost:8080"


def safe_request(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw or "{}")
        except Exception:
            return e.code, {"raw": raw}


def main():
    verdict = "NO_DEFECT"
    cls = "VeinShardEcho"
    try:
        safe_request("DELETE", "/v1/schema/" + cls)
    except Exception:
        pass

    s, _ = safe_request("POST", "/v1/schema", {
        "class": cls,
        "properties": [{"name": "num", "dataType": ["int"]}],
    })
    assert s == 200, "setup failed"
    gs, shards = safe_request("GET", "/v1/schema/%s/shards" % cls)
    shard = shards[0]["name"]

    # attack: invalid status on nonexistent shard
    sa, ra = safe_request("PUT", "/v1/schema/%s/shards/BOGUS_SHARD" % cls,
                          {"status": "NOT_A_STATUS"})
    print("attack bogus shard + bogus status: status=%s body=%s" % (
        sa, json.dumps(ra)))
    # attack: invalid status on real shard (control: correctly rejected)
    sc, rc = safe_request("PUT", "/v1/schema/%s/shards/%s" % (cls, shard),
                          {"status": "NOT_A_STATUS"})
    print("control real shard + bogus status: status=%s body=%s" % (
        sc, json.dumps(rc)[:160]))

    if sa == 200 and sc == 422:
        verdict = "DEFECT_FOUND"

    # cleanup: leave shard READY, drop class
    try:
        safe_request("PUT", "/v1/schema/%s/shards/%s" % (cls, shard),
                     {"status": "READY"})
        safe_request("DELETE", "/v1/schema/" + cls)
    except Exception:
        pass

    print("VERDICT: " + verdict)


if __name__ == "__main__":
    main()
