"""Map run3's 63 registered defects + 124 chains to submitted/unsubmitted,
using defect-N.md upstream references and the submission ledger issue numbers."""
import json
import glob
import re
import os

import openpyxl

P = "<HOME>/.claude/plugins/cache/testvdb/testvdb/2.5.0/results/qdrant/v1.18.0/2026-09-04T12-14-11Z"

# 1) ledger issue numbers (qdrant rows of the submission ledger)
wb = openpyxl.load_workbook("data/phase1_issue_classification.xlsx", data_only=True)
ws = wb["issues"]
hdr = [c.value for c in ws[1]]
ledger = {}
for r in ws.iter_rows(min_row=2):
    row = dict(zip(hdr, [c.value for c in r]))
    if row["vendor"] == "qdrant":
        ledger[str(row["number"])] = row
print(f"ledger qdrant rows: {len(ledger)}")

# 2) parse each defect-N.md for issue numbers it references
defect_info = {}
for f in sorted(glob.glob(f"{P}/defects/defect-*.md")):
    name = os.path.basename(f)[:-3]
    if "issue" in name or "mre" in name:
        continue
    s = open(f, encoding="utf-8", errors="replace").read()
    head = s[:400]
    issues = sorted(set(re.findall(r"#(\d{4,5})", s)) | set(re.findall(r"/issues/(\d{4,5})", s)),
                    key=lambda x: -int(x))
    defect_info[name] = {"issues": issues[:6], "head": re.sub(r"\s+", " ", head)[:160]}

print(f"registered defect reports: {len(defect_info)}")

submitted_linked = {}
unlinked = {}
for name, info in sorted(defect_info.items()):
    hits = [i for i in info["issues"] if i in ledger]
    if hits:
        submitted_linked[name] = hits
    else:
        unlinked[name] = info["issues"][:3]

print(f"\ndefects linked to ledger issues (submitted or tracked): {len(submitted_linked)}")
for k in list(submitted_linked)[:15]:
    print(f"  {k} -> ledger #{','.join(submitted_linked[k])}")
print(f"\ndefects with NO ledger link: {len(unlinked)}")
for k in list(unlinked)[:20]:
    print(f"  {k} -> refs {unlinked[k]}")

chains = [f for f in glob.glob(f"{P}/evidence_chain/*.json") if not f.endswith(".done")]
print(f"\nevidence chains: {len(chains)}")

json.dump({"submitted_linked": submitted_linked,
           "unlinked": unlinked},
          open(".tmp_task2_map.json", "w", encoding="utf-8"), indent=1)
print("map saved -> .tmp_task2_map.json")
