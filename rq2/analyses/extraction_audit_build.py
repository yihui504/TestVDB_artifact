"""Build the stratified extraction-audit sample.

Stratum A: contract rows embedded in the 81 RQ2 frozen packs (what judges judged against).
Stratum B: constraint rows from a broader extraction output (non-pack).
Seeded, reproducible. Output: .tmp_audit_sample.json
"""
import json
import random
import re

random.seed(20260911)

PACK_DIR = ".paperpilot/phase2-rerun/arms/materials_complete"
packs = sorted(
    __import__("os").listdir(PACK_DIR)
)

rows = []  # (origin_pack, row_dict)

# Pack constraint rows are fenced or inline JSON objects with constraint_id.
obj_re = re.compile(r"\{[^{}]*\"constraint_id\"[^{}]*\}", re.S)

for p in packs:
    s = open(f"{PACK_DIR}/{p}", encoding="utf-8", errors="replace").read()
    for m in obj_re.finditer(s):
        try:
            r = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict) and "constraint_id" in r:
            rows.append((p, r))

print(f"pack constraint rows parsed: {len(rows)} across {len(packs)} packs")

# Dedup by constraint_id (packs share rows across cases of the same version)
by_id = {}
for pack, r in rows:
    cid = r["constraint_id"]
    by_id.setdefault(cid, {"row": r, "packs": []})["packs"].append(pack)
print(f"unique constraint_ids in packs: {len(by_id)}")

# Stratified sample: 24 from packs (stratum A)
a_ids = sorted(by_id)
sample_a = random.sample(a_ids, min(24, len(a_ids)))

sample = []
for cid in sample_a:
    e = by_id[cid]
    sample.append({
        "stratum": "A_pack",
        "constraint_id": cid,
        "endpoint": e["row"].get("endpoint", ""),
        "description": e["row"].get("description", ""),
        "assertion": e["row"].get("assertion", e["row"].get("description", "")),
        "source_url": e["row"].get("source_url", ""),
        "doc_version": e["row"].get("doc_version", e["row"].get("ver", "")),
        "used_by_packs": e["packs"][:2],
    })

# Stratum B: structured_contract.json parameter constraints (non-pack).
# Build candidate records from qdrant v1.18.0 structured contract: endpoints with
# parameters carrying constraint-bearing descriptions.
B_TARGETS = [
    ("results/rq1-fullrun/qdrant-v1.18.0/structured_contract.json", "qdrant", "1.18.0"),
    ("results/rq1-fullrun/milvus-v2.6.16/structured_contract.json", "milvus", "2.6.16"),
]
b_rows = []
for path, vendor, ver in B_TARGETS:
    try:
        d = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        print("missing:", path)
        continue
    for ep in d.get("api_endpoints", []):
        for prm in ep.get("parameters", []):
            desc = str(prm.get("description", ""))
            # constraint-bearing: mentions ranges/must/default constraints
            if any(k in desc.lower() for k in ("must", "range", "minimum", "maximum", "default", "1 to", ">= ")):
                b_rows.append({
                    "stratum": "B_contract",
                    "constraint_id": f"{vendor}_{ver}_{ep['path'].replace('/', '_').replace('+', '_')}_{prm.get('name', 'na')}",
                    "endpoint": ep["path"],
                    "description": desc[:300],
                    "assertion": desc[:300],
                    "source_url": ep.get("source_url", ""),
                    "doc_version": str(ep.get("doc_version", ver)),
                    "used_by_packs": [],
                })
print(f"contract-side constraint-bearing rows: {len(b_rows)}")

sample_b = random.sample(b_rows, min(16, len(b_rows)))
sample += sample_b

random.shuffle(sample)
json.dump(sample, open(".tmp_audit_sample.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"final sample: {len(sample)} (A={len(sample_a)}, B={len(sample_b)})")
by_stratum = {}
for s in sample:
    by_stratum.setdefault(s["stratum"], []).append(s["constraint_id"])
for k, v in by_stratum.items():
    print(k, len(v))
