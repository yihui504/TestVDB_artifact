# state_import_jobs_08.py
# Attack: import jobs state machine — get_progress/describe on unknown job ids must be graceful
# Covers: jobs+import+list / jobs+import+get_progress / jobs+import+describe / jobs+import+create
# Focus: state machine error surfaces for invalid/unknown jobIDs (100 expected, 65535/HTTP 5xx = defect)
import os, sys, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR"); sys.exit(2)
BASE_URL = BASE_URL.rstrip("/")
H = {"Content-Type": "application/json", "Authorization": "Bearer root:Milvus"}
CLS = "stt_imp_08"

def safe_request(method, path, payload=None):
    try:
        r = requests.request(method, f"{BASE_URL}/v2/vectordb/{path}", headers=H, json=payload or {}, timeout=60)
        try: body = r.json()
        except Exception: body = None
        return r.status_code, body, r.text
    except Exception as e:
        return -1, None, f"EXC:{e}"

def verdict(v):
    print(f"VERDICT: {v}"); sys.exit(1 if v == "DEFECT_FOUND" else (2 if v == "SCRIPT_ERROR" else 0))

try:
    # 1. list jobs on non-existent collection -> graceful error (code!=0, not 65535-only generic)
    s, b, raw = safe_request("POST", "jobs/import/list", {"collectionName": CLS + "_nope"})
    print(f"import/list nonexistent coll: http={s} {raw[:200]}")
    if s >= 500: verdict("DEFECT_FOUND")
    if b is not None and b.get("code") == 0:
        # empty list is acceptable
        print("NOTE: empty success list for nonexistent collection")

    # 2. get_progress on bogus job id
    for jid in ("0", "999999999999", "not-a-job", "-1"):
        s, b, raw = safe_request("POST", "jobs/import/get_progress", {"jobID": jid})
        code = (b or {}).get("code")
        print(f"get_progress jobID={jid}: http={s} code={code} {raw[:160]}")
        if s >= 500:
            print(f"DEFECT: HTTP {s} for jobID={jid}"); verdict("DEFECT_FOUND")
        if code == 0:
            # succeeding progress on bogus id with state=failed is acceptable; state=Completed is not
            state = (((b or {}).get("data") or {})).get("state")
            print(f"  state={state}")
            if state in ("Completed", "ImportCompleted"):
                print(f"DEFECT: bogus jobID={jid} reports Completed"); verdict("DEFECT_FOUND")
        if code == 65535:
            # generic unexpected error surfaced to client for a user-input problem
            print(f"DEFECT: get_progress jobID={jid} -> generic 65535, expected specific 1xx code")
            verdict("DEFECT_FOUND")

    # 3. describe on bogus job id
    for jid in ("0", "not-a-job"):
        s, b, raw = safe_request("POST", "jobs/import/describe", {"jobID": jid})
        code = (b or {}).get("code")
        print(f"describe jobID={jid}: http={s} code={code} {raw[:160]}")
        if s >= 500: verdict("DEFECT_FOUND")
        if code == 0:
            state = (((b or {}).get("data") or {})).get("state")
            if state in ("Completed", "ImportCompleted"):
                print(f"DEFECT: bogus jobID={jid} describes Completed"); verdict("DEFECT_FOUND")
        if code == 65535:
            print(f"DEFECT: describe jobID={jid} -> generic 65535"); verdict("DEFECT_FOUND")

    # 4. create with malformed files spec -> parameter error (1800/1802 class), not 65535/5xx
    s, b, raw = safe_request("POST", "collections/create", {"collectionName": CLS, "dimension": 4})
    print(f"create: {raw[:80]}")
    s, b, raw = safe_request("POST", "jobs/import/create",
        {"collectionName": CLS, "files": ["s3://nonexistent-bucket/nope.json"]})
    code = (b or {}).get("code")
    print(f"import/create bogus file: http={s} code={code} {raw[:200]}")
    if s >= 500: verdict("DEFECT_FOUND")

    verdict("NO_DEFECT")
finally:
    try: safe_request("POST", "collections/drop", {"collectionName": CLS})
    except Exception: pass
