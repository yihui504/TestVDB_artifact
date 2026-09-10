# script_id: state_collections_delete_007
# strategy: delete_consistency
# endpoint: collections+delete
# Attack: qdrant_state_collections_delete_001 × timeout 边界 (query param timeout min 1)
#   覆盖: DELETE ?timeout=0 (低于文档 min 1) 与 DELETE ?timeout=1 (极小窗口) 下的状态一致性：
#   - 响应 200 => GET 必须 404（成功但僵尸 = Type4）
#   - 超时类响应 {400,408,423,504} 后，settle 2s 状态必须二选一完整：全删(GET 404+count 404) 或全在(GET 200+count 200)
#   - 半状态 (GET 200 但 count 404/500；或 GET 404 但 count 200) = Type4
#   - 500 需 census >= 2 才记 Type3（超时映射 500 视为低质量错误，单次只 OBSERVATION）
# constraint_ids: qdrant_state_collections_delete_001, qdrant_inv_collection_gone_after_delete_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
"""
Timeout-boundary delete state check. timeout=0 violates documented min 1 —
acceptance is recorded as OBSERVATION (weak validation, not state corruption);
DEFECT strictly requires state inconsistency (zombie-after-200, half-state) or
repeated 500s.
"""
import requests, json, sys, os, time

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")

def safe_request(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {"Content-Type": "application/json"})
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        status = resp.status_code
        text = resp.text
        try:
            body = resp.json() if text else {}
        except (json.JSONDecodeError, ValueError):
            return status, None, text
        return status, body, text
    except requests.exceptions.RequestException as e:
        print(f"REQUEST_ERROR: {e}")
        return 0, None, ""

TS = str(int(time.time()))
COLL = f"st_cdel_to_{TS}"
DIM = 8
N_POINTS = 300
BATCH = 100
TIMEOUT_CLASS = {400, 408, 423, 504}
five_hundreds = []

def cleanup():
    try:
        safe_request("DELETE", f"/collections/{COLL}?timeout=30")
    except Exception:
        pass

def defect(msg):
    print(msg)
    print("VERDICT: DEFECT_FOUND")
    sys.exit(1)

def build_collection():
    st, _, raw = safe_request("PUT", f"/collections/{COLL}",
                              json={"vectors": {"size": DIM, "distance": "Cosine"}})
    print(f"create: {st} {raw[:150]}")
    if st not in (200, 201):
        print("VERDICT: SCRIPT_ERROR")
        sys.exit(2)
    for b in range(N_POINTS // BATCH):
        pts = [{"id": b * BATCH + i, "vector": [0.01 * ((b * BATCH + i) % 7 + 1)] * DIM}
               for i in range(BATCH)]
        st, _, raw = safe_request("PUT", f"/collections/{COLL}/points?wait=true", json={"points": pts})
        if st not in (200, 201):
            print(f"seed batch {b}: {st} {raw[:150]}")
            print("VERDICT: SCRIPT_ERROR")
            sys.exit(2)
    print(f"seeded {N_POINTS} points")

def full_state_check(tag):
    """Return ('gone', None) / ('present', count) / raise defect on half-state or 5xx."""
    st_g, _, raw_g = safe_request("GET", f"/collections/{COLL}")
    st_c, body, raw_c = safe_request("POST", f"/collections/{COLL}/points/count", json={"exact": True})
    print(f"[{tag}] GET={st_g} count={st_c} raw_get={(raw_g or '')[:100]} raw_count={(raw_c or '')[:100]}")
    c = None
    if st_c == 200 and isinstance(body, dict) and isinstance(body.get("result"), dict):
        c = body["result"].get("count")
    # half-state detection
    if st_g == 200 and st_c == 404:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — [{tag}] half-state: GET 200 but count 404")
    if st_g == 404 and st_c == 200:
        defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — [{tag}] half-state: GET 404 but count 200 (count={c})")
    for stt, rrw, nm in ((st_g, raw_g, "GET"), (st_c, raw_c, "count")):
        if stt >= 500 or stt == 0:
            defect(f"VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — [{tag}] {nm} got {stt}: {(rrw or '')[:150]}")
    if st_g == 200:
        return "present", c
    return "gone", None

try:
    # round A: timeout=0 (below documented min 1)
    build_collection()
    st, _, raw = safe_request("DELETE", f"/collections/{COLL}?timeout=0")
    print(f"delete timeout=0: {st} {raw[:200]}")
    if st == 200:
        print("OBSERVATION: timeout=0 accepted with 200 (documented min is 1) — weak param validation, not scored")
    if st >= 500 or st == 0:
        five_hundreds.append(("delete_t0", st, (raw or "")[:120]))
    if st in (200, 201):
        state, _ = full_state_check("after_t0_200")
        if state == "present":
            defect("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — DELETE timeout=0 returned 200 but collection still present (success zombie)")
    elif st in TIMEOUT_CLASS or st == 404:
        time.sleep(2)
        state, _ = full_state_check("after_t0_timeout")
    time.sleep(0.5)

    # rounds B1..B3: timeout=1 on populated collection
    for rnd in range(1, 4):
        build_collection()
        st, _, raw = safe_request("DELETE", f"/collections/{COLL}?timeout=1")
        print(f"[round {rnd}] delete timeout=1: {st} {raw[:200]}")
        if st in (200, 201):
            state, _ = full_state_check(f"r{rnd}_after_200")
            if state == "present":
                defect(f"VERDICT: DEFECT_FOUND (Type4_StateLogicViolation) — round {rnd}: DELETE 200 but collection still present")
        elif st in TIMEOUT_CLASS:
            time.sleep(2)
            state, c = full_state_check(f"r{rnd}_after_timeout")
            print(f"[round {rnd}] settled state: {state} count={c}")
        elif st == 404:
            print(f"OBSERVATION: round {rnd} DELETE got 404 (previous delete completed late)")
        else:
            if st >= 500 or st == 0:
                five_hundreds.append((f"delete_t1_r{rnd}", st, (raw or "")[:120]))
            else:
                print(f"OBSERVATION: round {rnd} DELETE returned unexpected {st}")
            time.sleep(2)
            full_state_check(f"r{rnd}_after_unexpected")
        # ensure clean slate for next round
        cleanup()
        time.sleep(0.3)

    print(f"FIVE_HUNDRED_CENSUS: {len(five_hundreds)} (threshold 2)")
    for ev in five_hundreds:
        print(f"  5xx event: {ev}")
    if len(five_hundreds) >= 2:
        defect("VERDICT: DEFECT_FOUND (Type3_RuntimeFailure) — repeated 5xx on delete with tight timeout (>=2 confirms)")

    print("VERDICT: NO_DEFECT")
    sys.exit(0)
except SystemExit:
    raise
except Exception as e:
    print(f"UNEXPECTED_ERROR: {e}")
    print("VERDICT: SCRIPT_ERROR")
    sys.exit(2)
finally:
    cleanup()
