# -*- coding: utf-8 -*-
"""Shared runtime for boundary attack scripts (milvus v2.6.12 REST v2).
Contract-driven: no default port; BASE_URL from TESTVDB_DB_URL env.
Success = HTTP 200 + code:0. Error = HTTP 200 + non-zero code (Milvus v2 convention).
"""
import requests
import json
import os
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

AUTH = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}
V2 = "/v2/vectordb"


def base_url():
    b = os.environ.get("TESTVDB_DB_URL")
    if not b:
        print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set")
        sys.exit(2)
    return b.rstrip("/")


def safe_request(method, path, payload=None, timeout=90, raw_data=None):
    """All HTTP calls MUST go through this wrapper. Returns (status, body, raw_text)."""
    url = base_url() + path
    headers = dict(AUTH)
    try:
        r = requests.request(method, url, json=payload, data=raw_data,
                             headers=headers, timeout=timeout)
        raw = r.text
        try:
            body = r.json()
        except Exception:
            body = None
        return r.status_code, body, raw
    except Exception as e:
        return 0, None, "conn_err: %s" % e


def req(method, action, payload=None, timeout=90, raw_data=None):
    """REST v2 action call: req('POST','collections+create',{...})"""
    return safe_request(method, V2 + "/" + action.replace("+", "/"), payload,
                        timeout, raw_data)


def is_ok(status, body):
    """Milvus v2 success: HTTP 200 + code 0."""
    return status == 200 and isinstance(body, dict) and body.get("code") == 0


def cleanup_drop_collection(name):
    try:
        req("POST", "collections+drop", {"collectionName": name})
    except Exception:
        pass


def create_float_collection(name, dim=8, metric="L2", pk="id", vector_field="vector"):
    """Standard fixture: Int64 pk + FloatVector, auto-index, then load."""
    req("POST", "collections+drop", {"collectionName": name})
    st, bd, _ = req("POST", "collections+create", {
        "collectionName": name,
        "schema": {
            "autoId": False,
            "fields": [
                {"fieldName": pk, "dataType": "Int64", "isPrimary": True},
                {"fieldName": vector_field, "dataType": "FloatVector",
                 "elementTypeParams": {"dim": str(dim)}},
            ],
        },
        "indexParams": [{"fieldName": vector_field, "indexName": "vec_idx",
                         "metricType": metric, "params": {"index_type": "AUTOINDEX"}}],
    })
    if not is_ok(st, bd):
        return False, "create failed: %s" % bd
    st, bd, _ = req("POST", "collections+load", {"collectionName": name})
    return is_ok(st, bd), "load failed: %s" % bd
