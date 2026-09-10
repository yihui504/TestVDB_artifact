#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: state_collections_delete_002
# strategy: delete_consistency
# endpoint: collections+delete
# constraint_ids: qdrant_bc_delete_invisibility_001
# source_url: https://qdrant.tech/documentation/manage-data/collections/
# doc_version: unknown
"""
Attack: behavioral-contract invisibility sweep for delete on
  DELETE /collections/{name} (collections+delete; URL from raw_knowledge
  api_endpoints[].url). The contract's scenario is executed verbatim and
  extended to every state face: create -> upsert 5 points (wait=true) ->
  count==5 sanity -> DELETE (200) -> the collection must vanish from
  EVERY access face: (B) GET /collections list must no longer contain
  the name (items parsed via the "name" key); (C) GET
  /collections/{name} details must return 404; (D) the contract's
  exists leg (GET /collections/{c}/exists -> result.exists=false) is
  PROXIED by the describe 404 of leg (C) because the runtime PATHS
  whitelist exposes no exists path_key (SKIPPED direct exists probe:
  path_key whitelist — inventing keys is forbidden; a 404 describe IS
  the exists=false signal the contract wants); (E) the data face
  POST /collections/{name}/points/count must return 404 (a deleted
  collection must not answer counting with 200/stale counts);
  (F) GET /collections/{name}/points/{id} must return 404 (no
  point-level ghost). All faces probed IMMEDIATELY (no sleep — delete
  is synchronous) and again after a 2s settle (delayed resurrection /
  ghost reappearance is the same violation).
  [chunk_collections+delete coverage: delete_consistency x
   qdrant_bc_delete_invisibility_001 (list/get/exists/count/point
   faces after a 200 delete)]
Oracle: after a 200 delete -> name absent from list (200 response),
  describe 404, count 404, get_point 404 — both immediately and after
  2s settle. Any face still serving the deleted collection (200) =
  Type4_StateLogicViolation (stale visibility/ghost data); 5xx judged
  Type3 only after /healthz confirms liveness.
"""

import os
import sys
import json
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- bootstrap (three-layer fallback: env -> upward walk -> contract target) ----
_sd = os.environ.get("TESTVDB_SCRIPTS_DIR")
if not _sd:
    for _p in Path(__file__).resolve().parents:
        if (_p / "scripts" / "runtime" / "__init__.py").exists():
            _sd = str(_p / "scripts")
            break
if not _sd or not Path(_sd, "runtime", "__init__.py").exists():
    print("VERDICT: SCRIPT_ERROR - runtime scripts dir not found (TESTVDB_SCRIPTS_DIR unset)")
    sys.exit(2)
sys.path.insert(0, _sd)

if not os.environ.get("TESTVDB_TARGET"):
    for _p in Path(__file__).resolve().parents:
        _c = _p / "structured_contract.json"
        if _c.exists():
            try:
                _t = json.loads(_c.read_text(encoding="utf-8")).get("target", "")
                if _t:
                    os.environ["TESTVDB_TARGET"] = str(_t).lower()
            except Exception:
                pass
            break

try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)

BASE_URL = os.environ.get("TESTVDB_DB_URL")
if not BASE_URL:
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)


def safe_request(method, path_key, body=None, path_params=None,
                 query_params=None, timeout=30):
    """All HTTP through the runtime; timeout/path_params/body/query_params
    forwarded exactly; inline liveness probes stay visible to static checks."""
    return rt.request(method, path_key, body, path_params=path_params,
                      query_params=query_params, timeout=timeout)


def parse_json(raw):
    try:
        b = json.loads(raw) if raw else None
        return b if isinstance(b, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def list_names(raw):
    """List items parse via the "name" key (R11 standing lesson).
    Structural parse first; substring fallback flagged when used."""
    body = parse_json(raw)
    if body:
        res = body.get("result")
        if isinstance(res, dict):
            cols = res.get("collections")
            if isinstance(cols, list):
                return [c.get("name") for c in cols if isinstance(c, dict)], "structural"
    return None, "substring-fallback"


def main():
    TS = f"{int(time.time())}_{os.getpid()}"
    PFX = "scdl2_" + TS + "_"
    C = PFX + "invis"
    DIM = 4
    N_POINTS = 5
    DEFECTS = []

    def liveness(tag):
        _hs, _hraw = safe_request("GET", "healthz", timeout=10)
        print(f"[liveness {tag}] healthz status={_hs} raw={str(_hraw)[:120]}")
        return _hs == 200

    def probe_faces(phase):
        """(B) list, (C) describe / exists-proxy, (E) count, (F) get_point."""
        phase_defects = []
        # (B) list must be a working 200 and must NOT contain the name
        ls, lraw = safe_request("GET", "list_collections")
        print(f"[{phase} B list] status={ls} raw={str(lraw)[:200]}")
        if ls == 0 or 500 <= ls <= 599:
            if not liveness(f"{phase}-list"):
                return None  # SCRIPT_ERROR escalation
            phase_defects.append(f"[{phase}] list_collections returned {ls} with "
                                 f"service alive — Type3_RuntimeFailure — "
                                 f"raw={str(lraw)[:200]}")
        elif ls != 200:
            phase_defects.append(f"[{phase}] list_collections returned {ls} "
                                 f"(expected 200) — Type4_StateLogicViolation")
        else:
            names, mode = list_names(lraw)
            if names is None:
                present = C in (lraw or "")
                print(f"[{phase} B list] structural parse unavailable "
                      f"(mode={mode}) substring-present={present}")
                if present:
                    phase_defects.append(f"[{phase}] deleted collection still "
                                         f"present in list_collections "
                                         f"(substring, structural parse "
                                         f"unavailable) — Type4_StateLogicViolation "
                                         f"(qdrant_bc_delete_invisibility_001)")
            else:
                present = C in names
                print(f"[{phase} B list] mode={mode} names_n={len(names)} "
                      f"present={present}")
                if present:
                    phase_defects.append(f"[{phase}] deleted collection still "
                                         f"present in list_collections — "
                                         f"Type4_StateLogicViolation "
                                         f"(qdrant_bc_delete_invisibility_001)")
        # (C) describe -> 404 (also the exists=false proxy; see docstring)
        gs, graw = safe_request("GET", "describe_collection", path_params={"name": C})
        print(f"[{phase} C describe/exists-proxy] status={gs} raw={graw[:160]}")
        if gs == 0 or 500 <= gs <= 599:
            if not liveness(f"{phase}-describe"):
                return None
            phase_defects.append(f"[{phase}] describe after 200 delete returned "
                                 f"{gs} with service alive — Type3_RuntimeFailure "
                                 f"— raw={graw[:200]}")
        elif gs != 404:
            phase_defects.append(f"[{phase}] describe/exists-proxy after 200 delete "
                                 f"returned {gs} (expected 404 / exists=false) — "
                                 f"ghost collection state — "
                                 f"Type4_StateLogicViolation")
        # (E) count -> 404 (data face of a deleted collection)
        cs, craw = safe_request("POST", "count", path_params={"name": C},
                                body={"exact": True})
        print(f"[{phase} E count] status={cs} raw={craw[:160]}")
        if cs == 0 or 500 <= cs <= 599:
            if not liveness(f"{phase}-count"):
                return None
            phase_defects.append(f"[{phase}] count after 200 delete returned {cs} "
                                 f"with service alive — Type3_RuntimeFailure — "
                                 f"raw={craw[:200]}")
        elif cs != 404:
            phase_defects.append(f"[{phase}] count after 200 delete returned {cs} "
                                 f"(expected 404 — deleted collection must not "
                                 f"answer data faces) — Type4_StateLogicViolation "
                                 f"— raw={craw[:200]}")
        # (F) get_point -> 404 (no point-level ghost)
        ps, praw = safe_request("GET", "get_point", path_params={"name": C, "point_id": 1})
        print(f"[{phase} F get_point] status={ps} raw={praw[:160]}")
        if ps == 0 or 500 <= ps <= 599:
            if not liveness(f"{phase}-getpoint"):
                return None
            phase_defects.append(f"[{phase}] get_point after 200 delete returned "
                                 f"{ps} with service alive — Type3_RuntimeFailure "
                                 f"— raw={praw[:200]}")
        elif ps != 404:
            phase_defects.append(f"[{phase}] get_point after 200 delete returned "
                                 f"{ps} (expected 404) — point-level ghost — "
                                 f"Type4_StateLogicViolation")
        return phase_defects

    try:
        # ---- setup: create + points + count sanity ----
        cr_s, cr_raw = safe_request("PUT", "create_collection", path_params={"name": C},
                                    body={"vectors": {"size": DIM, "distance": "Cosine"}})
        print(f"[setup create] status={cr_s} raw={cr_raw[:200]}")
        if cr_s not in (200, 201):
            print("SETUP_ERROR: create failed — cannot judge invisibility contract")
            return "SCRIPT_ERROR"
        up_body = {"points": [{"id": i, "vector": [round(0.01 * (i + 1), 4)] * DIM}
                              for i in range(1, N_POINTS + 1)]}
        up_s, up_raw = safe_request("PUT", "upsert_points", path_params={"name": C},
                                    body=up_body, query_params={"wait": "true"})
        print(f"[setup upsert x{N_POINTS}] status={up_s} raw={up_raw[:160]}")
        if up_s not in (200, 201):
            print(f"SETUP_ERROR: upsert returned {up_s}")
            return "SCRIPT_ERROR"
        c0_s, c0_raw = safe_request("POST", "count", path_params={"name": C},
                                    body={"exact": True})
        c0_body = parse_json(c0_raw) or {}
        c0_val = ((c0_body.get("result") or {}).get("count")
                  if isinstance(c0_body.get("result"), dict) else None)
        print(f"[setup count] status={c0_s} count={c0_val} raw={c0_raw[:160]}")
        if c0_s != 200 or c0_val != N_POINTS:
            print(f"SETUP_ERROR: pre-delete count {c0_val} != {N_POINTS} (status {c0_s})")
            return "SCRIPT_ERROR"

        # ---- (A) the contract's DELETE -> 200 ----
        d_s, d_raw = safe_request("DELETE", "drop_collection", path_params={"name": C})
        print(f"[A delete] status={d_s} raw={d_raw[:200]}")
        if d_s == 0:
            liveness("A-delete")
            return "SCRIPT_ERROR"
        if 500 <= d_s <= 599 or d_s != 200:
            if 500 <= d_s <= 599 and not liveness("A-delete"):
                return "SCRIPT_ERROR"
            print(f"SETUP_ERROR: delete returned {d_s} — invisibility sweep "
                  f"requires a 200 delete as its premise")
            return "SCRIPT_ERROR"

        # ---- faces, immediate (no sleep: delete is synchronous) ----
        imm = probe_faces("immediate")
        if imm is None:
            return "SCRIPT_ERROR"
        DEFECTS.extend(imm)

        # ---- faces, settled (2s: delayed resurrection is the same violation) ----
        time.sleep(2)
        sett = probe_faces("settled")
        if sett is None:
            return "SCRIPT_ERROR"
        DEFECTS.extend(sett)

        if DEFECTS:
            for d in DEFECTS:
                print(f"DEFECT: {d}")
            return "DEFECT_FOUND"
        return "NO_DEFECT"
    finally:
        try:
            rt.drop_collection(C)
        except Exception:
            pass


if __name__ == "__main__":
    _v = main()
    print(f"VERDICT: {_v}")
    sys.exit(0 if _v == "NO_DEFECT" else 1 if _v == "DEFECT_FOUND" else 2)
