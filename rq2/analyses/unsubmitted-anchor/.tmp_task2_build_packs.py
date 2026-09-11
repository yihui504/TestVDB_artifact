"""Build frozen RQ2-format packs for run3's unsubmitted defect-confirming candidates.

Population: run3 defect registry defect-1..63 minus 4 ledger-linked (#9255 family) = 59.
Sample: 30 (seeded). Each pack = observed transcript (from the chain) + documented contract
row (from contract_grounding / structured_contract) — NO source grounding, NO cognition.
"""
import json
import glob
import re
import random
import os

random.seed(20260911)

P = "<HOME>/.claude/plugins/cache/testvdb/testvdb/2.5.0/results/qdrant/v1.18.0/2026-09-04T12-14-11Z"
OUT = ".tmp_task2_packs"
os.makedirs(OUT, exist_ok=True)

contract = json.load(open(
    "<HOME>/.claude/plugins/cache/testvdb/testvdb/2.5.0/results/qdrant/v1.18.0/structured_contract.json",
    encoding="utf-8"))
ep_row = {ep["path"]: ep for ep in contract["api_endpoints"]}

mapd = json.load(open(".tmp_task2_map.json", encoding="utf-8"))
population = sorted(set(mapd["unlinked"]))          # 59 unlinked defects
sample = random.sample(population, 30)
print(f"population={len(population)} sample={len(sample)}")

chains = {}
for f in glob.glob(f"{P}/evidence_chain/*.json"):
    if f.endswith(".done"):
        continue
    cid = os.path.basename(f)[:-5]
    chains[cid] = json.load(open(f, encoding="utf-8"))


def find_chain(defect_name):
    """Locate the chain a defect report was built from: the md cites its defect_id."""
    md = open(f"{P}/defects/{defect_name}.md", encoding="utf-8", errors="replace").read()
    ids = re.findall(r"\b((?:boundary|state|semantic|vein|bhvr)_[a-z0-9_]+_\d{1,3})\b", md)
    for cand in sorted(set(ids), key=lambda x: -md.count(x)):
        if cand in chains:
            return cand, chains[cand], md
    return None, None, md


def contract_row_for(ep_path, assertion):
    row = ep_row.get(ep_path)
    if not row:
        for k, v in ep_row.items():
            if k.split("+")[0] in (ep_path or ""):
                row = v
                break
    src = (row or {}).get("source_url", "")
    ver = (row or {}).get("doc_version", "")
    return src, ver


built, skipped = [], []
for defect_name in sample:
    cid, chain, md = find_chain(defect_name)
    if chain is None:
        skipped.append((defect_name, "chain-not-found"))
        continue
    steps = chain.get("steps", {})
    ee = steps.get("execution_evidence", {})
    cg = steps.get("contract_grounding", {})
    observed = "\n".join(
        [f"- {ee.get('log_pattern', '')}"] +
        [f"- {o}" for o in ee.get("secondary_observations", [])[:6]]
    ).strip()
    if not observed or observed == "-":
        skipped.append((defect_name, "no-observed"))
        continue
    ep_path = chain.get("endpoint", "")
    m = re.search(r"contract path: ([^)]+)\)", ep_path)
    ep_key = m.group(1) if m else ""
    src, ver = contract_row_for(ep_key, cg.get("assertion_text_quoted", ""))
    pack = f"""# 候选缺陷 {defect_name}

[vendor=qdrant endpoint={ep_key or 'unknown'}]

--- 观察到的行为（observed） ---

{observed}

--- 契约（expected，来自该版本文档/契约） ---

assertion: {cg.get('assertion_text_quoted', '(none)')}
source_url: {src}
doc_version: {ver}
"""
    fn = f"{OUT}/{defect_name}.md"
    open(fn, "w", encoding="utf-8").write(pack)
    built.append(defect_name)

print(f"built: {len(built)}  skipped: {len(skipped)}")
for s in skipped:
    print("  skip:", s)
json.dump(built, open(".tmp_task2_packs_list.json", "w", encoding="utf-8"), indent=1)
