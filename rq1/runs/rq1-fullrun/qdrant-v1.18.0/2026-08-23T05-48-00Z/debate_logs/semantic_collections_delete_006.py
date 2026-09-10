# script_id: semantic_collections_delete_006
# strategy: metamorphic
# endpoint: collections+delete
# Attack: alias-name vs real-name resource equivalence under delete (metamorphic relation: two
#         spellings of the same resource must yield consistent delete semantics) x
#         qdrant_bc_collection_delete_isolation_001 — incl. dangling-alias zombie reads after delete
# constraint_ids: qdrant_bc_collection_delete_isolation_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/delete-collection
# doc_version: 1.18.x (versioned)
# Blindspot: BS-05 semantic contract (alias/collection name resolution consistency)
# Block: chunk_collections+delete
# exploration_target: novel_candidate
"""Metamorphic: if a name (alias or real) resolves to a collection for READ,
then DELETE through that same name must have an effect consistent with the
read resolution — a 200 delete via alias followed by the real collection still
being readable is a hard state contradiction (Type4). Also: after deleting a
collection by its real name, a dangling alias must NOT serve its data (zombie
read = Type4). Dangling alias entries that only linger in the alias list
(without serving reads) are recorded as notes, not defects (contract-silent).
NOTE: alias body shape uses alias_name/collection_name (the R1
semantic_aliases_update_001 400 was caused by a wrong 'alias' key)."""
import os, sys, time, json, requests

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR — TESTVDB_DB_URL not set")
    sys.exit(2)
AUTH_HEADER = os.environ.get("TESTVDB_AUTH_HEADER", "")
TS = str(int(time.time()))


def safe_request(method, path, json_body=None, timeout=30):
    """(status, body, raw_text) triple — spec-mandated wrapper."""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    try:
        resp = requests.request(method, url, headers=headers,
                                json=json_body, timeout=timeout)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body, resp.text
    except Exception as e:
        return -1, str(e), str(e)


def drop_alias(alias):
    try:
        safe_request("POST", "/collections/aliases",
                     {"actions": [{"delete_alias": {"alias_name": alias}}]})
    except Exception:
        pass


def cleanup(name):
    try:
        safe_request("DELETE", f"/collections/{name}")
    except Exception:
        pass


N = f"sem_del_al_real_{TS}"
L = f"sem_del_al_als_{TS}"
try:
    # ---- part 1: delete THROUGH the alias ----
    s, _, raw = safe_request("PUT", f"/collections/{N}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"create {N}: {s} {raw[:150]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — create: {s}")
        sys.exit(2)
    s, _, raw = safe_request("PUT", f"/collections/{N}/points?wait=true",
                             {"points": [{"id": 1, "vector": [0.1, 0.2, 0.3, 0.4]}]})
    print(f"insert: {s} {raw[:120]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — insert: {s}")
        sys.exit(2)
    s, _, raw = safe_request("POST", "/collections/aliases",
                             {"actions": [{"create_alias":
                                           {"alias_name": L, "collection_name": N}}]})
    print(f"create_alias {L}->{N}: {s} {raw[:150]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — create_alias: {s} {raw[:200]}")
        sys.exit(2)

    s, _, raw = safe_request("GET", f"/collections/{L}")
    print(f"read via alias pre-delete: {s} {raw[:150]}")
    if s != 200:
        print("VERDICT: SCRIPT_ERROR — alias not resolvable for read; "
              "delete-via-alias comparison meaningless")
        sys.exit(2)

    s_del, _, raw_del = safe_request("DELETE", f"/collections/{L}")
    print(f"delete via alias {L}: {s_del} {raw_del[:200]}")
    if s_del == 0 or 500 <= s_del <= 599:
        print("VERDICT: SCRIPT_ERROR — transport/server error")
        sys.exit(2)
    if s_del == 200:
        # the read-resolved target must now be gone
        s, _, raw = safe_request("GET", f"/collections/{N}")
        print(f"read real name after alias-delete: {s} {raw[:150]}")
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print("DELETE via alias returned 200 but the underlying collection "
                  "is still readable — success reported with no effect")
            sys.exit(1)
        if s != 404:
            print(f"note: unexpected status {s} reading {N}")
        s, _, raw = safe_request("GET", f"/collections/{L}")
        print(f"read via alias after alias-delete: {s} {raw[:120]}")
        if s == 200:
            print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
            print("alias still resolves to data after its target was deleted "
                  "through the alias itself")
            sys.exit(1)
    else:
        # 4xx via alias: record the read/delete resolution asymmetry as note
        print(f"note: read via alias = 200 but delete via alias = {s_del} "
              "(resolution asymmetry recorded; contract-silent, not judged)")
        cleanup(N)

    # ---- part 2: dangling alias after real-name delete ----
    s, _, raw = safe_request("PUT", f"/collections/{N}",
                             {"vectors": {"size": 4, "distance": "Cosine"}})
    print(f"recreate {N}: {s} {raw[:120]}")
    if s not in (200, 201):
        print(f"VERDICT: SCRIPT_ERROR — recreate: {s}")
        sys.exit(2)
    s, _, raw = safe_request("PUT", f"/collections/{N}/points?wait=true",
                             {"points": [{"id": 7, "vector": [0.4, 0.3, 0.2, 0.1]}]})
    print(f"reinsert: {s} {raw[:120]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — reinsert: {s}")
        sys.exit(2)
    s, _, raw = safe_request("POST", "/collections/aliases",
                             {"actions": [{"create_alias":
                                           {"alias_name": L, "collection_name": N}}]})
    print(f"recreate_alias: {s} {raw[:120]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — recreate_alias: {s}")
        sys.exit(2)

    s, _, raw = safe_request("DELETE", f"/collections/{N}")
    print(f"delete real name: {s} {raw[:120]}")
    if s != 200:
        print(f"VERDICT: SCRIPT_ERROR — delete: {s}")
        sys.exit(2)

    s, _, raw = safe_request("GET", f"/collections/{L}")
    print(f"read via dangling alias: {s} {raw[:200]}")
    if s == 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("dangling alias still serves the deleted collection's data (zombie read)")
        sys.exit(1)
    # zombie point access through the dangling alias would be even worse
    s, _, raw = safe_request("GET", f"/collections/{L}/points/7")
    print(f"point read via dangling alias: {s} {raw[:150]}")
    if s == 200:
        print("VERDICT: DEFECT_FOUND (Type4_StateLogicViolation)")
        print("point of deleted collection readable through dangling alias")
        sys.exit(1)

    s, body, raw = safe_request("GET", "/collections/aliases")
    aliases = body.get("result", {}).get("aliases", []) \
        if isinstance(body, dict) else []
    linger = [a for a in aliases if a.get("alias_name") == L]
    if linger:
        print(f"note: dangling alias entry lingers in alias list: {linger} "
              "(cosmetic; contract-silent, not judged)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)
finally:
    drop_alias(L)
    cleanup(N)
