"""Shared helpers for milvus v2.6.12 attack scripts (contract-driven, REST v2)."""
import json, os, sys, time
import urllib.request, urllib.error

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
V2 = BASE_URL.rstrip("/") + "/v2/vectordb"
AUTH = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}


def safe_request(method, path, body=None, timeout=60):
    """Triple (status, body_dict_or_None, raw_text). Never raises."""
    url = V2 + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=AUTH, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:
        return -1, None, "EXC: %s" % e
    try:
        return status, json.loads(raw), raw
    except Exception:
        return status, None, raw


def code_of(body):
    if isinstance(body, dict):
        return body.get("code")
    return None


def ok(body):
    return code_of(body) == 0


def create_col(name, dim=4, metric="L2", extra_field=None):
    fields = [{"fieldName": "pk", "dataType": "Int64", "isPrimary": True, "autoID": False}]
    if extra_field:
        fields.append(extra_field)
    fields.append({"fieldName": "vec", "dataType": "FloatVector",
                   "elementTypeParams": {"dim": dim}})
    body = {"collectionName": name, "schema": {"fields": fields},
            "indexParams": [{"fieldName": "vec", "indexName": "vec_idx",
                             "metricType": metric, "indexType": "FLAT"}]}
    return safe_request("POST", "/collections/create", body)


def drop_col(name):
    try:
        safe_request("POST", "/collections/drop", {"collectionName": name})
    except Exception:
        pass


def wait_load(name, tries=40):
    for _ in range(tries):
        _, b, _ = safe_request("POST", "/collections/get_load_state",
                               {"collectionName": name})
        if isinstance(b, dict) and b.get("data", {}).get("loadState") in \
                ("LoadStateLoaded", "LoadStateNotExist"):
            return b.get("data", {}).get("loadState")
        time.sleep(1)
    return None


def flush(name):
    return safe_request("POST", "/collections/flush", {"collectionName": name})


def vec(v):
    return v
