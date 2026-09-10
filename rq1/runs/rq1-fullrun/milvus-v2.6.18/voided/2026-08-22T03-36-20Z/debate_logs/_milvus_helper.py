import os, sys, json, requests

BASE = os.environ.get("TESTVDB_DB_URL")
HDRS = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}

def safe_request(method, path_key, body=None, timeout=60):
    """path_key like 'collections+create' -> POST /v2/vectordb/collections/create.
    Returns (http_status, json_body_or_None, raw_text)."""
    if not BASE:
        raise RuntimeError("TESTVDB_DB_URL unset")
    url = BASE.rstrip("/") + "/v2/vectordb/" + path_key.replace("+", "/")
    try:
        r = requests.request(method, url, json=body, headers=HDRS, timeout=timeout)
        raw = r.text
        try:
            jb = r.json()
        except Exception:
            jb = None
        return r.status_code, jb, raw
    except Exception as e:
        return -1, None, "EXC: %s" % e

def code(b):
    return (b or {}).get("code", -999)

def drop(coll):
    try:
        safe_request("POST", "collections+drop", {"collectionName": coll})
    except Exception:
        pass

def row_count(coll):
    _, b, raw = safe_request("POST", "collections+get_stats", {"collectionName": coll})
    try:
        return int(b["data"]["rowCount"]), raw
    except Exception:
        return None, raw

def wait_flush(coll):
    """live v2.6.18: flush body key is 'collectionName' (singular string), NOT contract's 'collectionNames'."""
    try:
        s, b, raw = safe_request("POST", "collections+flush", {"collectionName": coll}, timeout=120)
        if code(b) != 0:
            print("flush warn:", raw[:120])
    except Exception as e:
        print("flush exc:", repr(e))
