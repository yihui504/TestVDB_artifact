#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# script_id: semantic_collections_get_004
# strategy: metamorphic
# endpoint: collections+get
# constraint_ids: qdrant_behavioral_collections_get_001
# source_url: https://api.qdrant.tech/v-1-18-x/api-reference/collections/get-collection
# doc_version: 1.18.x (versioned v-1-18-x api-reference)
# Blindspot: BS-05 (Documentation Drift - the read face is documented to
#   resolve aliases (proven this session on collections+exists: read faces
#   resolve, write faces do not); a describe-by-alias that returns a
#   different config than describe-by-real-name, an unstable repeated
#   describe, or a stale alias still serving a 200 config after its target
#   was dropped, is exactly the documented-behavior-vs-implementation
#   drift this blindspot covers)
"""
Attack: metamorphic (S6) x qdrant_behavioral_collections_get_001 on
  collections+get (chunk_collections+get unit
  assertions::qdrant_behavioral_collections_get_001; R14 dispatch: "alias
  interplay fair game (describe resolves aliases - proven this session:
  read face resolves, write faces don't)").
  Metamorphic relations (declared before measurement, G7):
    R-equivalence - describe(n) == describe(a) on config content whenever a
                    is a live alias of n (both names route to ONE
                    collection, so params.vectors, params.shard_number,
                    params.replication_factor, hnsw_config.m,
                    points_count and result.status must be identical)
    R-stability   - describe(n) repeated must be deep-equal on the whole
                    result.config object and equal on points_count (a
                    config is immutable absent updates; no field may flap)
    R-membership  - n appears in list_collections names; a never-created
                    unique-prefix name does not (an alias appearing in the
                    collections list is printed as an observed note only -
                    list-lane territory)
    R-stale       - after n is dropped with a live alias a2->n remaining,
                    describe(a2) must be 404 (the assertion's miss branch),
                    never a stale 200-with-config
  Probes (G4 both directions on one setup):
    P1 baseline    - create C (+2 points, wait=true); describe(C) -> 200
    P2 equivalence - create_alias al->C; describe(al) -> 200 and identical
                     to P1 on every R-equivalence field
    P3 stability   - describe(C) again -> deep-equal config, equal counters
    P4 membership  - list_collections contains C; never-created name absent
    P5 stale       - create_alias al2->C, drop C (if the drop is refused,
                     the refusal is the delete face's documented right -
                     leg skipped with a printed note, G3); describe(al2)
                     -> 404 with an error message, never 200
  [chunk_collections+get coverage: metamorphic x
   qdrant_behavioral_collections_get_001 (alias equivalence + stability +
   membership + stale-alias miss) - this script; 200-full-config grid vs
   404 = _001; config-echo = _002; counter truthfulness = _003; error-body
   quality = _005; legal-name family = _006]
Oracle: P2 describe(alias) returns 200 and matches describe(real-name) on
  config.params.vectors, params.shard_number, params.replication_factor,
  hnsw_config.m, points_count and result.status - any field differing =
  Type4_StateLogicViolation (one collection, two configs); a non-200 on
  the live alias = Type1_IllegalRejection (the read face resolves
  aliases); P3 second describe(C) is deep-equal on result.config and equal
  on points_count - any flap = Type4 (unstable read); P4 C present and
  never-created name absent from list names - violation = Type4; P5
  describe(al2) after the target's 200 drop returns 404 with a non-empty
  error message - 200-with-config = Type1_IllegalSuccess (stale config
  served through a dead alias), non-404 = Type4; alias action failures =
  SCRIPT_ERROR (setup premise); 5xx with /healthz alive = Type3;
  transport failure with healthy /healthz = SCRIPT_ERROR (G8).

Rationale (G6/G9): the destructive mutation point is P5 - dropping the
  target while the alias map still points at it decouples the name space
  from the collection state at the exact moment the read face must
  reconcile them, which is where an alias-resolution cache most easily
  goes stale and serves a phantom config. R-equivalence is the strongest
  available identity oracle because the describe response echoes no name
  field at all: two names describing one collection MUST be
  indistinguishable on content.
"""

import os
import sys
import json
import time
import uuid
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- X1 bootstrap three-layer fallback: env -> upward walk -> contract target ----
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
if os.environ.get("TESTVDB_TARGET", "").lower() != "qdrant":
    print(f"VERDICT: SCRIPT_ERROR - contract target mismatch (expected qdrant, got {os.environ.get('TESTVDB_TARGET')!r})")
    sys.exit(2)
try:
    from runtime import get_runtime
    rt = get_runtime()
except Exception as e:
    print(f"VERDICT: SCRIPT_ERROR - runtime import failed: {e}")
    sys.exit(2)
if not os.environ.get("TESTVDB_DB_URL"):
    print("VERDICT: SCRIPT_ERROR - TESTVDB_DB_URL not set (see agents/_target_api_reference.md)")
    sys.exit(2)

# describe face: runtime PATHS key describe_collection, cross-checked against
# raw_knowledge api_endpoints[path=collections+get].url = /collections/{collection_name}
DESCRIBE_KEY = "describe_collection"
print(f"[path derivation] {DESCRIBE_KEY} = {rt.PATHS[DESCRIBE_KEY]} "
      f"(runtime PATHS; matches raw_knowledge api_endpoints[collections+get].url "
      f"/collections/{{collection_name}})")

PFX = "scg04" + uuid.uuid4().hex[:6]  # unique per-script ownership prefix
DIM = 4

# R-equivalence field set: dotted paths under result
EQUIV_FIELDS = [
    ("config.params.vectors", ("config", "params", "vectors")),
    ("config.params.shard_number", ("config", "params", "shard_number")),
    ("config.params.replication_factor", ("config", "params", "replication_factor")),
    ("config.hnsw_config.m", ("config", "hnsw_config", "m")),
    ("points_count", ("points_count",)),
    ("status", ("status",)),
]


def safe_request(method, path_key, **kw):
    """Thin delegation to rt.request (DB-neutral path_key; forwards body/
    path_params/query_params/timeout exactly - standing lesson)."""
    return rt.request(method, path_key, **kw)


def healthz_ladder(label, attempts=3, delay=2):
    """G8 liveness re-check: inline safe_request('GET','healthz') probes."""
    for i in range(attempts):
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[healthz attempt {i + 1}] status={hs} raw={str(hraw)[:120]}")
        if 200 <= hs < 300:
            return None
        if i < attempts - 1:
            time.sleep(delay)
    return (f"Type3_RuntimeFailure(service-down) - '{label}': /healthz unreachable "
            f"after {attempts} attempts")


def transport_gate(label, st, raw, findings):
    """Three-outcome isolation (G8): True if adjudicable, False after recording."""
    if st <= 0:
        v = healthz_ladder(label)
        if v:
            findings.append((1, v))
        else:
            findings.append((3, f"SCRIPT-ERROR-transport: '{label}' failed with healthy /healthz: {str(raw)[:150]}"))
        return False
    if 500 <= st <= 599:
        v = healthz_ladder(label)
        findings.append((1, v if v else
                         f"Type3_RuntimeFailure: '{label}' got {st} with /healthz alive; body: {str(raw)[:200]}"))
        return False
    return True


def describe_result(name):
    """GET /collections/{name} -> (status, raw, result_object_or_None)."""
    st, raw = safe_request("GET", DESCRIBE_KEY,
                           path_params={"name": name}, timeout=30)
    try:
        env = json.loads(raw) if raw else None
    except (json.JSONDecodeError, ValueError, TypeError):
        env = None
    res = env.get("result") if isinstance(env, dict) else None
    return st, raw, res


def dig(obj, path):
    node = obj
    for k in path:
        if isinstance(node, dict) and k in node:
            node = node[k]
        else:
            return None
    return node


def extract_error(env):
    if not isinstance(env, dict):
        return None
    st = env.get("status")
    if isinstance(st, dict) and isinstance(st.get("error"), str) and st.get("error"):
        return st["error"]
    for k in ("err", "error", "message", "detail"):
        v = env.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def alias_action(action, findings, label):
    """POST one aliases+update action; returns True on 200 result=true."""
    st, raw = safe_request("POST", "update_aliases",
                           body={"actions": [action]}, timeout=30)
    print(f"[{label}] status={st} raw={str(raw)[:220]}")
    if not transport_gate(label, st, raw, findings):
        return False
    ok = False
    try:
        env = json.loads(raw) if raw else {}
        ok = isinstance(env.get("result"), bool) and env["result"]
    except (json.JSONDecodeError, ValueError, TypeError):
        ok = False
    if st != 200 or not ok:
        findings.append((3, f"SCRIPT-ERROR-setup: alias action '{label}' returned "
                            f"{st} (envelope ok={ok}); alias premise broken: {str(raw)[:150]}"))
        return False
    return True


def list_names():
    """GET /collections -> names list or None (key extraction first, R11)."""
    st, raw = safe_request("GET", "list_collections", timeout=30)
    if st != 200:
        return None
    try:
        res = json.loads(raw).get("result")
        colls = res.get("collections") if isinstance(res, dict) else None
        if isinstance(colls, list):
            return [c.get("name") for c in colls if isinstance(c, dict)]
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        pass
    return None


def main():
    print(f"ownership prefix: {PFX}")
    findings = []
    real = PFX + "_real"   # the underlying collection (self-created)
    al1 = PFX + "_al1"     # alias for the equivalence leg
    al2 = PFX + "_al2"     # alias kept live across the target drop
    never = PFX + "_never"  # never-created name (membership negative)
    try:
        hs, hraw = safe_request("GET", "healthz", timeout=15)
        print(f"[pre-probe] /healthz status={hs} raw={str(hraw)[:80]}")
        if hs != 200:
            print(f"VERDICT: SCRIPT_ERROR - /healthz pre-probe returned {hs}")
            sys.exit(2)

        # ---- P1 baseline: create C with 2 committed points, describe by name ----
        st, raw = safe_request("PUT", "create_collection",
                               body={"vectors": {"size": DIM, "distance": "Cosine"}},
                               path_params={"name": real}, timeout=60)
        print(f"[create {real}] status={st} raw={str(raw)[:200]}")
        if not transport_gate("create real", st, raw, findings):
            finish(findings)
            return
        if st not in (200, 201):
            findings.append((3, f"SCRIPT-ERROR-setup: create returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return
        pts = [{"id": i, "vector": [0.1 * (i + 1)] * DIM} for i in (1, 2)]
        st, raw = safe_request("PUT", "upsert_points", body={"points": pts},
                               path_params={"name": real},
                               query_params={"wait": "true"}, timeout=60)
        print(f"[upsert 2 points wait=true] status={st} raw={str(raw)[:200]}")
        if not transport_gate("upsert real", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((3, f"SCRIPT-ERROR-setup: upsert returned {st}: {str(raw)[:150]}"))
            finish(findings)
            return
        st, raw, base = describe_result(real)
        print(f"[P1 describe {real}] status={st} raw={str(raw)[:300]}")
        if not transport_gate("P1 describe real", st, raw, findings):
            finish(findings)
            return
        if st != 200 or not isinstance(base, dict):
            findings.append((2, f"Type1_IllegalRejection: P1 - describe of an existing "
                                f"collection returned HTTP {st} (result object: "
                                f"{isinstance(base, dict)}); "
                                f"qdrant_behavioral_collections_get_001 requires 200 "
                                f"with config: {str(raw)[:200]!r}"))
            finish(findings)
            return

        # ---- P2 equivalence: describe by live alias must match the baseline ----
        if not alias_action({"create_alias": {"collection_name": real, "alias_name": al1}},
                            findings, f"create_alias {al1}->{real}"):
            finish(findings)
            return
        st, raw, via_alias = describe_result(al1)
        print(f"[P2 describe {al1}] status={st} raw={str(raw)[:300]}")
        if not transport_gate("P2 describe alias", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            findings.append((2, f"Type1_IllegalRejection: P2 - describe by live alias "
                                f"{al1!r} returned HTTP {st}; the read face is "
                                f"documented to resolve aliases (assertion's existing-"
                                f"collection branch): {str(raw)[:200]!r}"))
        elif not isinstance(via_alias, dict):
            findings.append((2, f"Type4_StateLogicViolation: P2 - alias-routed 200 but "
                                f"result is not an object (grid: result=object)"))
        else:
            for label, path in EQUIV_FIELDS:
                v1, v2 = dig(base, path), dig(via_alias, path)
                if v1 != v2:
                    findings.append((2, f"Type4_StateLogicViolation: P2 - R-equivalence "
                                        f"broken on {label}: describe({real})={v1!r} "
                                        f"but describe({al1})={v2!r} - one underlying "
                                        f"collection must not expose two configs"))
                else:
                    print(f"[conform] P2 {label} identical via alias ({v1!r})")

        # ---- P3 stability: repeated describe must not flap ----
        st, raw, again = describe_result(real)
        print(f"[P3 describe {real} again] status={st} raw={str(raw)[:300]}")
        if not transport_gate("P3 describe again", st, raw, findings):
            finish(findings)
            return
        if st != 200 or not isinstance(again, dict):
            findings.append((2, f"Type1_IllegalRejection: P3 - repeated describe "
                                f"returned HTTP {st} (result object: "
                                f"{isinstance(again, dict)}): {str(raw)[:200]!r}"))
        else:
            c1 = dig(base, ("config",))
            c2 = dig(again, ("config",))
            if c1 != c2:
                findings.append((2, f"Type4_StateLogicViolation: P3 - R-stability "
                                    f"broken: result.config flapped between two reads "
                                    f"of the same unchanged collection: "
                                    f"{json.dumps(c1, default=str)[:200]} vs "
                                    f"{json.dumps(c2, default=str)[:200]}"))
            else:
                print("[conform] P3 result.config deep-equal across repeats")

        # ---- P4 membership: list contains C, not the never-created name ----
        names = list_names()
        print(f"[P4 list_collections] names={names!r}")
        if names is None:
            print("[note] P4 list_collections unavailable - membership leg skipped (G3)")
        else:
            if real not in names:
                findings.append((2, f"Type4_StateLogicViolation: P4 - {real!r} is "
                                    f"describe-able with 200 but absent from "
                                    f"list_collections (faces disagree on existence)"))
            if never in names:
                findings.append((2, f"Type4_StateLogicViolation: P4 - never-created "
                                    f"{never!r} appears in list_collections"))
            if al1 in names:
                print(f"[observed note] P4: alias {al1!r} appears in the collections "
                      f"list - list-lane territory, not adjudicated here (G3)")
            if real in names and never not in names:
                print("[conform] P4 membership agrees with describe")

        # ---- P5 stale alias: drop target, alias must no longer serve config ----
        if not alias_action({"create_alias": {"collection_name": real, "alias_name": al2}},
                            findings, f"create_alias {al2}->{real}"):
            finish(findings)
            return
        st, raw = safe_request("DELETE", "drop_collection",
                               path_params={"name": real}, timeout=120)
        print(f"[drop {real} with live alias {al2}] status={st} raw={str(raw)[:220]}")
        if not transport_gate("drop real (stale-alias leg)", st, raw, findings):
            finish(findings)
            return
        if st != 200:
            print(f"[note] drop of an alias-bearing collection returned {st} - "
                  f"disposition belongs to the delete lane; P5 adjudication leg "
                  f"skipped (G3)")
        else:
            st, raw = describe_result(al2)
            try:
                env = json.loads(raw) if raw else None
            except (json.JSONDecodeError, ValueError, TypeError):
                env = None
            err = extract_error(env)
            print(f"[P5 describe stale {al2}] status={st} error={err!r} "
                  f"raw={str(raw)[:240]}")
            if st == 200:
                findings.append((2, f"Type1_IllegalSuccess: P5 - describe through "
                                    f"stale alias {al2!r} returned 200 with a config "
                                    f"after its target collection {real!r} was dropped "
                                    f"with 200; the assertion's miss branch requires "
                                    f"404, never 200 with config: {str(raw)[:200]!r}"))
            elif st != 404:
                findings.append((2, f"Type4_StateLogicViolation: P5 - documented miss "
                                    f"answer is 404, describe through stale alias "
                                    f"{al2!r} got {st}: {str(raw)[:200]!r}"))
            elif not err:
                findings.append((2, f"Type4_StateLogicViolation: P5 - 404 with no error "
                                    f"message through stale alias {al2!r} (assertion: "
                                    f"'404 with an error message')"))
            else:
                print("[conform] P5 stale alias answers 404 with an error message")

        finish(findings)
    finally:
        # cleanup: self-created aliases first, then the collection; all try/except
        for al in (al1, al2):
            try:
                safe_request("POST", "update_aliases",
                             body={"actions": [{"delete_alias": {"alias_name": al}}]},
                             timeout=15)
            except Exception as e:
                print(f"cleanup warning (delete_alias {al}): {e}")
        try:
            rt.drop_collection(real)
        except Exception as e:
            print(f"cleanup warning (drop {real}): {e}")


def finish(findings):
    if findings:
        findings.sort(key=lambda x: x[0])
        rank, msg = findings[0]
        if rank == 3:
            print(f"VERDICT: SCRIPT_ERROR - {msg}")
            sys.exit(2)
        print(f"VERDICT: DEFECT_FOUND ({msg})")
        sys.exit(1)
    print("OK: metamorphic relations hold - describe(real) == describe(alias) on "
          "all equivalence fields, repeated describes are deep-equal, list "
          "membership agrees, and a stale alias answers 404 (never a phantom "
          "200-with-config)")
    print("VERDICT: NO_DEFECT")
    sys.exit(0)


if __name__ == "__main__":
    main()
